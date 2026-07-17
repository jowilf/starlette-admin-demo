"""App-specific field validators, layered on top of the built-ins in
`starlette_admin.validators` (`number_range`, `email`, etc.).

A validator is a callable `(request, field, value)` raising `ValueError` to
reject a value; attach it to a field via `validators=[...]`. Use these for
any check that only needs that one field's value. Reserve a view's
`validate()` override for genuinely cross-field rules, where a field's
validity depends on another field's value (e.g. `end_date >= start_date`)
or requires assembling several fields into one message.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette_admin.fields import BaseField
from starlette_admin.i18n import lazy_gettext as _


def positive(message: str | None = None):
    """Requires `value > 0`.

    Complements `starlette_admin.validators.number_range`, which is
    inclusive and so can't express a strict lower bound of zero.
    """

    def validate(request: Request, field: BaseField, value: Any) -> None:
        if value <= 0:
            raise ValueError(message or _("Must be greater than zero."))

    return validate


def unique(model: type, column: Any, message: str | None = None):
    """Requires no other row of `model` to have `column == value`.

    Assumes `model`'s primary key column is `id`. Reads the object being
    edited from `request.query_params["pk"]` (present on edit/inline-edit
    forms) and excludes it from the check, so resubmitting a row's own
    value isn't rejected as a collision with itself.

    Example: `EmailField("email", validators=[unique(Employee, Employee.email)])`.
    """

    def validate(request: Request, field: BaseField, value: Any) -> None:
        session: Session = request.state.session
        query = select(column).where(column == value)
        pk = request.query_params.get("pk")
        if pk is not None and pk.isdigit():
            query = query.where(model.id != int(pk))
        if session.execute(query).first() is not None:
            raise ValueError(message or _("This value is already taken."))

    return validate
