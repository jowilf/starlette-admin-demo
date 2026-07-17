"""Read-only audit trail. `AuditSubscriber` writes one `AuditLog` row per
create/edit/delete/export/import event, admin-wide (subscribed in app.py).

Uses the `*_COMMITTED` events, not `AFTER_CREATE`/`AFTER_EDIT`/`AFTER_DELETE`:
`request.state.session` doesn't commit until the request ends, so the plain
`AFTER_*` events can still be rolled back. Each handler opens its own session
rather than reuse the request's, per the `after_*_committed` hook contract.

Row/bulk actions (`adjust_budget`, `deactivate`, `approve`/`reject` in
views.py) bypass create()/edit()/delete() and never fire those events, so
they call `log_action()` directly through `request.state.session` instead,
committing atomically with the action itself.
"""

from datetime import datetime
from typing import Any

import anyio
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column
from starlette.requests import Request
from starlette_admin import RowActionsDisplayType, RowActionsPosition
from starlette_admin.contrib.sqla import ModelView
from starlette_admin.events import (
    AdminEvent,
    AdminEventSubscriber,
    AfterCreateContext,
    AfterDeleteContext,
    AfterEditContext,
    AfterExportContext,
    AfterImportContext,
    on,
)

from .config import engine
from .models import Base

# Not `__admin_repr__`: some models (LeaveRequest, Timesheet) build their repr
# via a relationship, which risks DetachedInstanceError in *_COMMITTED hooks.
_LABEL_ATTRS = ("name", "title", "expense_number", "slug", "email")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    event: Mapped[str] = mapped_column(String(50))
    resource: Mapped[str] = mapped_column(String(100))
    record_pk: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(200), nullable=True)

    async def __admin_repr__(self, request: Request) -> str:
        return self.detail or f"{self.event} {self.resource}#{self.record_pk}"


class AuditLogView(ModelView):
    """Rows come only from `AuditSubscriber`/`log_action()`; not editable by any role.

    Doesn't subclass `views.ModelView` (would be circular: that module imports
    `log_action` from here), so shared cosmetic settings are repeated below.
    """

    row_actions_display_type = RowActionsDisplayType.KEBAB
    row_actions_position = RowActionsPosition.AFTER_COLUMNS
    show_goto_page = True
    row_actions = ["view"]
    fields_default_sort = [("created_at", True)]

    def can_create(self, request: Request) -> bool:
        return False

    def can_edit(self, request: Request) -> bool:
        return False

    def can_delete(self, request: Request) -> bool:
        return False

    def can_import(self, request: Request) -> bool:
        return False


def _actor(request: Request) -> str:
    user = getattr(request.state, "admin_user", None)
    return getattr(user, "username", None) or "system"


def _label(obj: Any) -> str | None:
    for attr in _LABEL_ATTRS:
        value = getattr(obj, attr, None)
        if value:
            return str(value)
    return None


def _describe(verb: str, resource: str, obj: Any, pk: Any) -> str:
    label = _label(obj)
    detail = f"{verb} {resource!r}"
    if label:
        detail += f": {label!r}"
    return f"{detail} (pk={pk})"


async def _write_audit(
    request: Request, event: AdminEvent | str, resource: str, pk: Any, detail: str
) -> None:
    event_str = event.value if isinstance(event, AdminEvent) else str(event)
    actor = _actor(request)

    def _insert() -> None:
        with Session(engine) as session:
            session.add(
                AuditLog(
                    event=event_str,
                    resource=resource,
                    record_pk=str(pk) if pk is not None else None,
                    detail=detail,
                    actor=actor,
                    created_at=datetime.utcnow(),
                )
            )
            session.commit()

    await anyio.to_thread.run_sync(_insert)


def log_action(request: Request, resource: str, pk: Any, detail: str) -> None:
    """Log a row/bulk action that bypasses create()/edit()/delete().

    Call after staging the mutation on `request.state.session`, so the audit
    row commits (or rolls back) with the action's own transaction.
    """
    session: Session = request.state.session
    session.add(
        AuditLog(
            event="action",
            resource=resource,
            record_pk=str(pk) if pk is not None else None,
            detail=detail,
            actor=_actor(request),
            created_at=datetime.utcnow(),
        )
    )


class AuditSubscriber(AdminEventSubscriber):
    """Subscribed admin-wide: `admin.events.subscribe(AuditSubscriber())`."""

    @on(AdminEvent.AFTER_CREATE_COMMITTED)
    async def record_create(self, ctx: AfterCreateContext) -> None:
        await _write_audit(
            ctx.request,
            ctx.event,
            ctx.resource,
            ctx.pk,
            _describe("Created", ctx.resource, ctx.obj, ctx.pk),
        )

    @on(AdminEvent.AFTER_EDIT_COMMITTED)
    async def record_edit(self, ctx: AfterEditContext) -> None:
        await _write_audit(
            ctx.request,
            ctx.event,
            ctx.resource,
            ctx.pk,
            _describe("Edited", ctx.resource, ctx.obj, ctx.pk),
        )

    @on(AdminEvent.AFTER_DELETE_COMMITTED)
    async def record_delete(self, ctx: AfterDeleteContext) -> None:
        await _write_audit(
            ctx.request,
            ctx.event,
            ctx.resource,
            ctx.pk,
            _describe("Deleted", ctx.resource, ctx.obj, ctx.pk),
        )

    @on(AdminEvent.AFTER_EXPORT)
    async def record_export(self, ctx: AfterExportContext) -> None:
        detail = (
            f"Exported {ctx.row_count} row(s) from {ctx.resource!r} "
            f"as {ctx.export_type.extension}"
        )
        await _write_audit(ctx.request, ctx.event, ctx.resource, None, detail)

    @on(AdminEvent.AFTER_IMPORT)
    async def record_import(self, ctx: AfterImportContext) -> None:
        detail = (
            f"Imported {ctx.row_count} row(s) into {ctx.resource!r} "
            f"as {ctx.import_type.extension}"
        )
        if ctx.error_count:
            detail += f" ({ctx.error_count} error(s))"
        await _write_audit(ctx.request, ctx.event, ctx.resource, None, detail)
