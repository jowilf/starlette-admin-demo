"""Custom fields for the admin: `DollarField`, `AvatarNameField`, `BadgeField` and its per-enum subclasses, and `ProgressField`; see each class's docstring for specifics."""

from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import Enum
from typing import Any

from starlette.requests import Request
from starlette_admin.fields import ComputedField, DecimalField, EnumField, StringField
from starlette_admin.storage.local import LocalStorage
from starlette_admin.types import RequestAction


class DollarField(DecimalField):
    """A `DecimalField` whose list/detail display is dollar-formatted."""

    async def serialize_value(self, request: Request, value: Any) -> Any:
        if value is not None and request.state.action in (
            RequestAction.LIST,
            RequestAction.DETAIL,
        ):
            return f"${value:,.2f}"
        return await super().serialize_value(request, value)


def name_initials(name: str) -> str:
    """Initials for an avatar circle when no image is uploaded; shared by `AvatarNameField` and the employee profile header so both match."""
    parts = name.split()
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0][:2].upper() if len(parts[0]) > 1 else parts[0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


class AvatarNameField(StringField):
    """Renders `name` together with a circular avatar image on the list page."""

    def __init__(
        self,
        avatars_storage: LocalStorage,
        **kwargs,
    ):
        super().__init__("name", list_template="fields/avatar_name.html", **kwargs)
        self.avatars_storage = avatars_storage

    async def parse_obj(self, request: Request, obj: Any) -> Any:
        name = await super().parse_obj(request, obj)
        avatar_key = None
        if obj.avatar is not None:
            avatar_key = obj.avatar.get("key")
        return {
            "name": name,
            "avatar_key": avatar_key,
            "initials": name_initials(name),
        }

    async def serialize_value(self, request: Request, value: Any) -> Any:
        name, avatar_key = value.get("name"), value.get("avatar_key")
        if request.state.action != RequestAction.LIST:
            return name
        if avatar_key is not None:
            value["avatar_url"] = await self.avatars_storage.url(request, avatar_key)
        return value


@dataclass
class BadgeField(EnumField):
    """Base class rendering an enum value as a colored badge with an icon.

    Looks up color/icon in `badge_class_by_value`/`icon_by_value` by the enum's raw value, falling back to a plain badge if unmapped; subclasses fill in those two mappings for one specific enum.
    """

    list_template: str = "fields/badge.html"
    detail_template: str = "fields/badge.html"
    badge_class_by_value: dict[str, str] = dc_field(default_factory=dict)
    icon_by_value: dict[str, str] = dc_field(default_factory=dict)

    async def serialize_value(self, request: Request, value: Any) -> Any:
        label = await super().serialize_value(request, value)
        if request.state.action in (
            RequestAction.EDIT,
            RequestAction.INLINE_EDIT,
            RequestAction.EXPORT,
        ):
            return label
        raw = value.value if isinstance(value, Enum) else value
        return {
            "label": label.title(),
            "badge_class": self.badge_class_by_value.get(raw, "badge"),
            "icon": self.icon_by_value.get(raw),
        }


@dataclass
class EmploymentTypeBadgeField(BadgeField):
    """Renders `employment_type` as a colored badge with an icon."""

    badge_class_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "full_time": "badge bg-success-lt",
            "part_time": "badge bg-azure-lt",
            "contractor": "badge bg-orange-lt",
            "intern": "badge",
        }
    )
    icon_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "full_time": "fa-solid fa-briefcase",
            "part_time": "fa-solid fa-business-time",
            "contractor": "fa-solid fa-file-signature",
            "intern": "fa-solid fa-graduation-cap",
        }
    )


@dataclass
class LeaveTypeBadgeField(BadgeField):
    """Renders `LeaveRequest.type` as a colored badge with an icon."""

    badge_class_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "annual": "badge bg-azure-lt",
            "sick": "badge bg-danger-lt",
            "personal": "badge bg-purple-lt",
            "unpaid": "badge",
            "parental": "badge bg-teal-lt",
        }
    )
    icon_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "annual": "fa-solid fa-umbrella-beach",
            "sick": "fa-solid fa-briefcase-medical",
            "personal": "fa-solid fa-user",
            "unpaid": "fa-solid fa-ban",
            "parental": "fa-solid fa-baby",
        }
    )


@dataclass
class LeaveStatusBadgeField(BadgeField):
    """Renders `LeaveRequest.status` as a colored badge with an icon."""

    badge_class_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "pending": "badge bg-warning-lt",
            "approved": "badge bg-success-lt",
            "rejected": "badge bg-danger-lt",
            "taken": "badge bg-primary-lt",
            "cancelled": "badge",
        }
    )
    icon_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "pending": "fa-solid fa-clock",
            "approved": "fa-solid fa-check",
            "rejected": "fa-solid fa-xmark",
            "taken": "fa-solid fa-plane-departure",
            "cancelled": "fa-solid fa-ban",
        }
    )


@dataclass
class ProjectStatusBadgeField(BadgeField):
    """Renders `Project.status` as a colored badge, matching the colors Filament's `ProjectStatus` enum assigns to each case."""

    badge_class_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "planning": "badge",
            "active": "badge bg-success-lt",
            "on_hold": "badge bg-warning-lt",
            "completed": "badge bg-azure-lt",
            "cancelled": "badge bg-danger-lt",
        }
    )
    icon_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "planning": "fa-solid fa-pen-to-square",
            "active": "fa-solid fa-play",
            "on_hold": "fa-solid fa-pause",
            "completed": "fa-solid fa-circle-check",
            "cancelled": "fa-solid fa-xmark",
        }
    )


@dataclass
class TaskPriorityBadgeField(BadgeField):
    """Renders a `TaskPriority` value as a colored badge, matching Filament's colors; used for both `Project.priority` and `Task.priority`, which share this enum."""

    badge_class_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "low": "badge",
            "medium": "badge bg-azure-lt",
            "high": "badge bg-warning-lt",
            "critical": "badge bg-danger-lt",
        }
    )
    icon_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "low": "fa-solid fa-chevron-down",
            "medium": "fa-solid fa-minus",
            "high": "fa-solid fa-chevron-up",
            "critical": "fa-solid fa-fire",
        }
    )


@dataclass
class TaskStatusBadgeField(BadgeField):
    """Renders `Task.status` as a colored badge, matching the colors Filament's `TaskStatus` enum assigns to each case."""

    badge_class_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "backlog": "badge",
            "todo": "badge bg-azure-lt",
            "in_progress": "badge bg-warning-lt",
            "in_review": "badge bg-primary-lt",
            "completed": "badge bg-success-lt",
            "cancelled": "badge bg-danger-lt",
        }
    )
    icon_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "backlog": "fa-solid fa-inbox",
            "todo": "fa-solid fa-list-check",
            "in_progress": "fa-solid fa-arrow-rotate-right",
            "in_review": "fa-solid fa-eye",
            "completed": "fa-solid fa-circle-check",
            "cancelled": "fa-solid fa-circle-xmark",
        }
    )


@dataclass
class ExpenseStatusBadgeField(BadgeField):
    """Renders `Expense.status` as a colored badge, matching the colors Filament's `ExpenseStatus` enum assigns to each case."""

    badge_class_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "draft": "badge",
            "submitted": "badge bg-azure-lt",
            "approved": "badge bg-success-lt",
            "rejected": "badge bg-danger-lt",
            "reimbursed": "badge bg-primary-lt",
        }
    )
    icon_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "draft": "fa-solid fa-pen",
            "submitted": "fa-solid fa-paper-plane",
            "approved": "fa-solid fa-check",
            "rejected": "fa-solid fa-xmark",
            "reimbursed": "fa-solid fa-money-bill-wave",
        }
    )


@dataclass
class ExpenseCategoryBadgeField(BadgeField):
    """Renders `Expense.category` as a colored badge, matching the colors Filament's `ExpenseCategory` enum assigns to each case."""

    badge_class_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "travel": "badge bg-azure-lt",
            "meals": "badge bg-orange-lt",
            "supplies": "badge bg-teal-lt",
            "equipment": "badge bg-purple-lt",
            "software": "badge bg-blue-lt",
            "other": "badge",
        }
    )
    icon_by_value: dict[str, str] = dc_field(
        default_factory=lambda: {
            "travel": "fa-solid fa-plane",
            "meals": "fa-solid fa-utensils",
            "supplies": "fa-solid fa-box",
            "equipment": "fa-solid fa-toolbox",
            "software": "fa-solid fa-laptop-code",
            "other": "fa-solid fa-ellipsis",
        }
    )


@dataclass
class ProgressField(ComputedField):
    """Progress bar for `actual_hours` vs `estimated_hours`, colored by whether the work is on track, done, or over estimate."""

    list_template: str = "fields/progress.html"
    detail_template: str = "fields/progress.html"

    def compute(self, obj: Any) -> dict[str, Any]:
        estimated, actual = obj.estimated_hours, obj.actual_hours
        if not estimated:
            return {"width": 0, "bar_class": "bg-secondary", "label": "No estimate"}
        percent = round(float(actual) / float(estimated) * 100)
        bar_class = (
            "bg-danger"
            if percent > 100
            else "bg-success"
            if percent == 100
            else "bg-primary"
        )
        return {
            "width": min(percent, 100),
            "bar_class": bar_class,
            "label": f"{percent}%",
        }

    async def serialize_value(self, request: Request, value: Any) -> Any:
        if request.state.action in (RequestAction.EDIT, RequestAction.EXPORT):
            return value.get("label")
        return value
