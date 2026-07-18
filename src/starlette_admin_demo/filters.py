"""Custom filters for the Employee list's `department` field, since `RelationField`s only get null-checks by default."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette_admin.filters.base import (
    BaseFilter,
    FilterApplyContext,
    FilterDataType,
    FilterValidationError,
)
from starlette_admin.filters.enum import InFilter, NotInFilter

from .models import Department, Employee


class DepartmentContainsFilter(BaseFilter):
    """Employees whose department name contains this substring, case-insensitive."""

    name = "department_contains"
    label = "name contains"
    data_type = FilterDataType.STRING

    def apply(self, ctx: FilterApplyContext) -> Any:
        column = getattr(ctx.view.model, ctx.field_name)
        return column.has(Department.name.ilike(f"%{ctx.value}%"))


class _DepartmentChoicesMixin:
    """Shared `get_choices`/`parse_value` for the two filters below: the dropdown lists departments by name but posts back `id`, so `apply` matches on the primary key."""

    def get_choices(self, request: Request) -> list[tuple[int, str]]:
        session: Session = request.state.session
        return list(
            session.execute(
                select(Department.id, Department.name).order_by(Department.name)
            ).all()
        )

    def parse_value(self, raw: Any) -> list[int]:
        values = super().parse_value(raw)  # type: ignore[misc]
        try:
            return [int(v) for v in values]
        except ValueError as err:
            raise FilterValidationError("Department id must be an integer") from err


class DepartmentInFilter(_DepartmentChoicesMixin, InFilter):
    """Employees in one of the selected departments."""

    name = "department_in"
    label = "is one of"

    def apply(self, ctx: FilterApplyContext) -> Any:
        return Employee.department_id.in_(ctx.value)


class DepartmentNotInFilter(_DepartmentChoicesMixin, NotInFilter):
    """Employees not in any selected department, including those with none."""

    name = "department_not_in"
    label = "is not one of"

    def apply(self, ctx: FilterApplyContext) -> Any:
        return ~Employee.department_id.in_(ctx.value)
