"""App-specific field validators, layered on top of the built-ins in `starlette_admin.validators` (`number_range`, `email`, etc.).

Reserve a view's `validate()` override for genuinely cross-field rules (e.g. `end_date >= start_date`).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette_admin.fields import BaseField
from starlette_admin.i18n import lazy_gettext as _


def unique(model: type, column: Any, message: str | None = None):
    """Requires no other row of `model` to have `column == value`, excluding the object being edited so resubmitting its own value isn't rejected as a collision with itself.

    The edit form carries the current pk as a `pk` query param; import (which has
    no query param) falls back to `id` in `form_values`.

    Example: `EmailField("email", validators=[unique(Employee, Employee.email)])`.
    """

    def validate(
        request: Request, field: BaseField, value: Any, form_values: dict[str, Any]
    ) -> None:
        session: Session = request.state.session
        query = select(column).where(column == value)
        pk = request.query_params.get("pk") or form_values.get("id")
        if pk is not None and str(pk).isdigit():
            query = query.where(model.id != int(pk))
        if session.execute(query).first() is not None:
            raise ValueError(message or _("This value is already taken."))

    return validate
