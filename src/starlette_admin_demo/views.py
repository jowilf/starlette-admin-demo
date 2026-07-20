"""Admin views. `SoftDeleteModelView` gives any model mixing in `SoftDeleteMixin` (see models.py) "delete hides the row" behavior for free.

`searchable_fields` on a view only drives its filter builder; the search bar itself always matches the model's `search_vector` (see search.py).
"""

from collections import Counter
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import anyio
from markupsafe import escape
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette_admin import (
    ActionSelection,
    CollectionField,
    ColorField,
    FieldRef,
    FieldsetWidget,
    HasOne,
    ImageField,
    ListField,
    PanelWidget,
    RowActionsDisplayType,
    RowActionsPosition,
    StringField,
    TabsWidget,
    TagsField,
    TextWidget,
    action,
    flash,
    row_action,
)
from starlette_admin.contrib.sqla import InlineModelView as BaseInlineModelView
from starlette_admin.contrib.sqla import ModelView as BaseModelView
from starlette_admin.contrib.sqla.filters import IsNotNullFilter, IsNullFilter
from starlette_admin.exceptions import ActionFailed, FormValidationError
from starlette_admin.fields import (
    DecimalField,
    EmailField,
    IntegerField,
    SlugField,
    TextAreaField,
)
from starlette_admin.helpers import on_commit
from starlette_admin.validators import email, length, number_gt, number_range, slug

from .audit import log_action
from .cache import trigger_dashboard_refresh
from .config import avatars_storage
from .fields import (
    AvatarNameField,
    DollarField,
    EmploymentTypeBadgeField,
    ExpenseCategoryBadgeField,
    ExpenseStatusBadgeField,
    LeaveStatusBadgeField,
    LeaveTypeBadgeField,
    ProgressField,
    ProjectStatusBadgeField,
    TaskPriorityBadgeField,
    TaskStatusBadgeField,
    name_initials,
)
from .filters import (
    DepartmentContainsFilter,
    DepartmentInFilter,
    DepartmentNotInFilter,
)
from .models import (
    Department,
    Employee,
    EmploymentType,
    Expense,
    ExpenseCategory,
    ExpenseLine,
    ExpenseStatus,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Project,
    ProjectStatus,
    Task,
    TaskPriority,
    TaskStatus,
)
from .search import fts_match
from .validators import unique

# ── Soft-delete base views ───────────────────────────────────────────────────


class ModelView(BaseModelView):
    """Share common configuration across all views."""

    row_actions_display_type = RowActionsDisplayType.KEBAB
    row_actions_position = RowActionsPosition.AFTER_COLUMNS
    show_goto_page = True
    search_auto_submit = True
    # Every format in starlette_admin's EXPORT_FORMATS registry (tablib[all] + reportlab
    # are project dependencies, so all of these are available).
    exporters = [
        "csv",
        "tsv",
        "json",
        "yaml",
        "xlsx",
        "xls",
        "ods",
        "dbf",
        "html",
        "latex",
        "jira",
        "rst",
        "pdf",
    ]
    # Every format in starlette_admin's IMPORT_FORMATS registry.
    importers = ["csv", "tsv", "json", "yaml", "xlsx", "xls", "ods", "dbf", "html"]

    def get_search_query(self, request: Request, term: str) -> Any:
        # Replaces the library's per-column ILIKE scan with the model's GIN-indexed `search_vector` (models.py / search.py).
        # The vector already folds in related rows' names, so this single clause is the whole search.
        return fts_match(self.model, term)

    @staticmethod
    def _is_reader(request: Request) -> bool:
        user = getattr(request.state, "admin_user", None)
        return getattr(user, "role", None) == "reader"

    def can_create(self, request: Request) -> bool:
        return not self._is_reader(request)

    def can_edit(self, request: Request) -> bool:
        return not self._is_reader(request)

    def can_delete(self, request: Request) -> bool:
        return not self._is_reader(request)

    def can_import(self, request: Request) -> bool:
        return not self._is_reader(request)

    async def is_action_allowed(self, request, name):
        if self._is_reader(request):
            return False
        return await super().is_action_allowed(request, name)

    async def is_row_action_allowed(self, request, name):
        # Readers keep "view"; every other row action is write-shaped.
        if self._is_reader(request) and name != "view":
            return False
        return await super().is_row_action_allowed(request, name)


class SoftDeleteModelView(ModelView):
    """Base view for a model mixing in SoftDeleteMixin.

    Hides trashed rows from the list/count/detail queries, and turns "delete"
    into stamping `deleted_at` rather than issuing a SQL DELETE.
    """

    exclude_fields_from_list = ["deleted_at"]
    exclude_fields_from_create = ["deleted_at"]
    exclude_fields_from_edit = ["deleted_at"]

    def get_list_query(self, request: Request):
        return super().get_list_query(request).where(self.model.deleted_at.is_(None))

    def get_count_query(self, request: Request):
        return super().get_count_query(request).where(self.model.deleted_at.is_(None))

    def get_detail_query(self, request: Request):
        return super().get_detail_query(request).where(self.model.deleted_at.is_(None))

    async def delete(self, request: Request, pks: list[Any]) -> int | None:
        session: Session = request.state.session
        objs = await self.find_by_pks(request, pks)
        now = datetime.utcnow()
        for obj in objs:
            await self._emit_before_delete(request, obj.id, obj)
            obj.deleted_at = now
            session.add(obj)
        session.flush()

        def _make_after_delete_committed(obj: Any, pk: Any) -> Callable[[], Any]:
            return lambda: self._emit_after_delete_committed(request, pk, obj)

        for obj in objs:
            pk = obj.id
            await self._emit_after_delete(request, pk, obj)
            on_commit(request, _make_after_delete_committed(obj, pk))
        return len(objs)


class InlineModelView(BaseInlineModelView):
    extra = 0


# ── Department ───────────────────────────────────────────────────────────────


class DepartmentView(ModelView):
    fields = [
        "id",
        StringField(
            "name",
            required=True,
            validators=[length(max=200)],
        ),
        SlugField(
            "slug",
            populate_from="name",
            required=True,
            validators=[
                slug(),
                unique(
                    Department,
                    Department.slug,
                    message="A department with this slug already exists.",
                ),
            ],
        ),
        TextAreaField(
            "description",
            validators=[length(max=2000)],
        ),
        DollarField(
            "budget",
            help_text="Annual budget allocated to the department, in USD.",
            validators=[number_range(min=0, max=1_000_000_000)],
        ),
        IntegerField(
            "headcount",
            validators=[number_range(min=0, max=100_000)],
        ),
        ColorField(
            "color",
            validators=[length(max=20)],
        ),
        "is_active",
        HasOne(
            "parent",
            key="department",
            null_template="fields/detail/_department_parent_null.html",
        ),
    ]
    exclude_fields_from_list = ["id", "description"]
    fields_default_sort = ["name"]
    # search_vector also folds in the parent department's name.
    searchable_fields = [
        "name",
        "slug",
        "budget",
        "headcount",
        "is_active",
        "parent",
    ]
    sortable_fields = ["name", "slug", "budget", "headcount", "is_active"]
    # Quick edits from the list page, without opening the full form.
    inline_editable_fields = ["is_active", "headcount"]
    form_layout = [
        FieldsetWidget(legend="Identity", children=[("name", "slug"), "description"]),
        PanelWidget(
            title="Structure",
            children=[("parent", "headcount"), ("color", "is_active")],
        ),
        PanelWidget(
            title="Budget",
            children=[
                TextWidget(
                    content="Prefer the 'Adjust budget' row action for changes",
                ),
                FieldRef("budget", prepend="$", show_label=False),
            ],
        ),
    ]

    row_actions = ["view", "adjust_budget", "edit", "delete"]

    @staticmethod
    def _build_adjust_budget_form(_request: Request, obj: Any) -> str:
        return f"""
        <form>
            <div class="mt-3">
                <label class="form-label">New budget for {escape(obj.name)}</label>
                <input type="number" class="form-control" name="new_budget"
                       value="{obj.budget:.2f}" step="0.01">
            </div>
        </form>
        """

    @row_action(
        name="adjust_budget",
        text="Adjust budget",
        confirmation="Set this department's new budget.",
        icon_class="fa-solid fa-sack-dollar",
        submit_btn_text="Apply",
        submit_btn_class="btn-success",
        action_btn_class="btn-info",
        form=_build_adjust_budget_form,
    )
    async def adjust_budget_row_action(self, request: Request, pk: Any) -> None:
        session: Session = request.state.session
        data = await request.form()
        try:
            new_budget = Decimal(data.get("new_budget"))
        except (InvalidOperation, TypeError) as err:
            raise ActionFailed("Enter a valid amount.") from err
        if new_budget < 0:
            raise ActionFailed("Budget cannot be reduced below zero.")
        department = await self.find_by_pk(request, pk)
        delta = new_budget - department.budget
        department.budget = new_budget
        session.add(department)
        session.flush()  # the session is committed automatically at the end of each request
        on_commit(request, trigger_dashboard_refresh)
        delta_sign = "+" if delta >= 0 else "-"
        log_action(
            request,
            self.key,
            department.id,
            f"Adjusted {department.name!r} budget by {delta_sign}${abs(delta):,.2f}, "
            f"new total: ${new_budget:,.2f}",
        )
        flash(
            request,
            f"{department.name}'s budget was adjusted by {delta_sign}${abs(delta):,.2f}, "
            f"new total: ${new_budget:,.2f}.",
            "success",
        )

    @action(
        name="deactivate",
        text="Deactivate selected departments",
        confirmation="Are you sure you want to deactivate the selected departments?",
        submit_btn_text="Yes, deactivate",
        submit_btn_class="btn-outline-danger",
    )
    async def deactivate_action(
        self, request: Request, selection: ActionSelection
    ) -> None:
        session: Session = request.state.session
        departments = await selection.rows()
        for department in departments:
            department.is_active = False
            session.add(department)
        session.flush()  # the session is committed automatically at the end of each request
        on_commit(request, trigger_dashboard_refresh)
        for department in departments:
            log_action(
                request, self.key, department.id, f"Deactivated {department.name!r}"
            )
        flash(
            request,
            f"{len(departments)} department(s) were deactivated.",
            "success",
        )


# ── Employee (soft-deletable) ────────────────────────────────────────────────


class EmployeeView(SoftDeleteModelView):
    """Detail page is `templates/employee/detail.html`, a hand-built profile body in place of the stock attribute/value table.

    It receives this view as `view` and calls `initials`/`tenure` directly for date/string logic.
    """

    detail_template = "employee/detail.html"

    fields = [
        "id",
        ImageField(
            "avatar",
            storage=avatars_storage,
            upload_folder="avatars",
            exclude_from_list=True,
            max_size=200 * 1024,  # 200 KB
        ),
        AvatarNameField(
            avatars_storage=avatars_storage,
            required=True,
            validators=[length(max=200)],
        ),
        EmailField(
            "email",
            required=True,
            validators=[
                email(),
                length(max=200),
                unique(
                    Employee,
                    Employee.email,
                    message="An employee with this email already exists.",
                ),
            ],
        ),
        StringField(
            "phone",
            validators=[length(max=40)],
        ),
        "date_of_birth",
        StringField(
            "job_title",
            required=True,
            validators=[length(max=200)],
        ),
        EmploymentTypeBadgeField("employment_type", enum=EmploymentType),
        DollarField(
            "salary",
            help_text="Annual salary in USD.",
            validators=[
                number_gt(0),
                number_range(max=1_000_000),
            ],
        ),
        "hire_date",
        TagsField("skills", label="Skills"),
        ListField(
            CollectionField(
                "metadata_",
                fields=[
                    StringField(
                        "property",
                        validators=[length(max=100)],
                    ),
                    StringField(
                        "value",
                        validators=[length(max=500)],
                    ),
                ],
            ),
        ),
        "is_active",
        HasOne(
            "department",
            key="department",
            filters=[
                DepartmentContainsFilter,
                DepartmentInFilter,
                DepartmentNotInFilter,
                IsNullFilter,
                IsNotNullFilter,
            ],
        ),
        "deleted_at",
    ]
    exclude_fields_from_list = [
        *SoftDeleteModelView.exclude_fields_from_list,
        "id",
        "phone",
        "date_of_birth",
        "skills",
        "metadata_",
    ]
    # search_vector also folds in the department's name.
    searchable_fields = [
        "name",
        "email",
        "job_title",
        "employment_type",
        "salary",
        "hire_date",
        "is_active",
        "department",
    ]
    sortable_fields = [
        "name",
        "email",
        "job_title",
        "employment_type",
        "salary",
        "hire_date",
        "is_active",
    ]
    fields_default_sort = ["name"]
    # Quick edits from the list page, without opening the full form.
    inline_editable_fields = ["is_active", "job_title", "salary", "department"]
    form_layout = [
        TabsWidget(
            tabs=[
                (
                    "Basic Info",
                    [
                        "avatar",
                        ("name", FieldRef("email", prepend="@")),
                        ("job_title", "hire_date"),
                    ],
                ),
                (
                    "Details",
                    [
                        ("phone", "date_of_birth"),
                        ("employment_type", "department"),
                        "is_active",
                    ],
                ),
                ("Additional Info", ["skills", "metadata_"]),
                (
                    "Compensation",
                    [
                        TextWidget(content="Visible to HR only.", card=False),
                        FieldRef("salary", prepend="$"),
                    ],
                ),
            ]
        ),
    ]

    async def validate(self, request: Request, data: dict[str, Any]) -> None:
        # Cross-field only: salary and email are checked by their own field validators (see the `salary`/`email` fields above).
        errors: dict[str, str] = {}
        date_of_birth = data.get("date_of_birth")
        hire_date = data.get("hire_date")
        if date_of_birth is not None and hire_date is not None:
            working_age_cutoff = date(
                hire_date.year - 16, hire_date.month, hire_date.day
            )
            if date_of_birth > working_age_cutoff:
                errors["date_of_birth"] = (
                    "Employee must be at least 16 years old as of the hire date."
                )
        if errors:
            raise FormValidationError(errors)
        await super().validate(request, data)

    @staticmethod
    def initials(name: str) -> str:
        """Fallback for the profile header avatar when no image is uploaded, matching the list page chip rendered by `AvatarNameField`."""
        return name_initials(name)

    @staticmethod
    def tenure(obj: Any) -> str:
        """Human-readable time since `hire_date`, e.g. "3 years, 4 months"."""
        days = (date.today() - obj.hire_date).days
        if days < 0:
            return "Starts soon"
        years, remainder = divmod(days, 365)
        months = remainder // 30
        if years and months:
            return f"{years} year{'s' if years > 1 else ''}, {months} month{'s' if months > 1 else ''}"
        if years:
            return f"{years} year{'s' if years > 1 else ''}"
        if months:
            return f"{months} month{'s' if months > 1 else ''}"
        return f"{days} day{'s' if days != 1 else ''}"


# ── LeaveRequest ─────────────────────────────────────────────────────────────


class LeaveRequestView(ModelView):
    fields = [
        "id",
        HasOne("employee", key="employee", required=True),
        "approver",
        LeaveTypeBadgeField("type", enum=LeaveType),
        LeaveStatusBadgeField("status", enum=LeaveStatus),
        "start_date",
        "end_date",
        "start_time",
        "end_time",
        DecimalField(
            "days_requested",
            required=True,
            validators=[
                number_gt(0),
                number_range(max=999.9),
            ],
        ),
        TextAreaField(
            "reason",
            required=True,
            validators=[length(max=2000)],
        ),
        TextAreaField(
            "reviewer_notes",
            validators=[length(max=2000)],
        ),
        "reviewed_at",
    ]
    exclude_fields_from_list = ["id", "reason", "reviewer_notes"]
    fields_default_sort = [("start_date", True)]
    # search_vector also covers list-excluded reason/reviewer_notes and folds in the employee's and approver's names.
    searchable_fields = [
        "type",
        "status",
        "start_date",
        "end_date",
        "days_requested",
        "reviewed_at",
        "employee",
        "approver",
    ]
    sortable_fields = [
        "start_date",
        "end_date",
        "days_requested",
        "status",
        "type",
        "reviewed_at",
    ]
    # Quick edits from the list page, without opening the full form.
    inline_editable_fields = ["status"]
    form_layout = [
        FieldsetWidget(
            legend="Request",
            children=[
                ("employee", "type"),
                ("start_date", "end_date"),
                ("start_time", "end_time"),
                "days_requested",
                "reason",
            ],
        ),
        PanelWidget(
            title="Review",
            children=[
                TextWidget(
                    content="Normally set through the Approve/Reject row "
                    "actions; edit directly only to correct a mistake.",
                    card=False,
                ),
                ("approver", "status"),
                "reviewer_notes",
                "reviewed_at",
            ],
            collapsible=True,
            collapsed=True,
        ),
    ]

    row_actions = ["view", "approve", "reject", "edit", "delete"]
    actions = ["approve", "reject"]

    async def validate(self, request: Request, data: dict[str, Any]) -> None:
        # Cross-field only: days_requested has its own field validator (see the `days_requested` field above).
        errors: dict[str, str] = {}
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        if start_date is not None and end_date is not None and end_date < start_date:
            errors["end_date"] = "End date must be on or after the start date."
        if errors:
            raise FormValidationError(errors)
        await super().validate(request, data)

    async def is_row_action_allowed_for_obj(
        self, request: Request, name: str, obj: Any
    ) -> bool:
        if name in ("approve", "reject"):
            return obj.status == LeaveStatus.PENDING
        return await super().is_row_action_allowed_for_obj(request, name, obj)

    @row_action(
        name="approve",
        text="Approve",
        confirmation="Approve this leave request?",
        icon_class="fa-solid fa-check",
        submit_btn_text="Yes, approve",
        submit_btn_class="btn-success",
        action_btn_class="btn-success",
    )
    async def approve_row_action(self, request: Request, pk: Any) -> None:
        leave_request = await self.find_by_pk(request, pk)
        self._review(request, [leave_request], LeaveStatus.APPROVED)
        flash(
            request,
            f"{leave_request.employee.name}'s leave request was approved.",
            "success",
        )

    @row_action(
        name="reject",
        text="Reject",
        confirmation="Reject this leave request?",
        icon_class="fa-solid fa-xmark",
        submit_btn_text="Yes, reject",
        submit_btn_class="btn-danger",
        action_btn_class="btn-danger",
    )
    async def reject_row_action(self, request: Request, pk: Any) -> None:
        leave_request = await self.find_by_pk(request, pk)
        self._review(request, [leave_request], LeaveStatus.REJECTED)
        flash(
            request,
            f"{leave_request.employee.name}'s leave request was rejected.",
            "success",
        )

    @action(
        name="approve",
        text="Approve selected leave requests",
        confirmation="Approve the selected leave requests? Requests that "
        "aren't pending are left untouched.",
        submit_btn_text="Yes, approve",
        submit_btn_class="btn-success",
        icon_class="fa-solid fa-check",
    )
    async def approve_action(
        self, request: Request, selection: ActionSelection
    ) -> None:
        leave_requests = await selection.rows()
        pending = [lr for lr in leave_requests if lr.status == LeaveStatus.PENDING]
        self._review(request, pending, LeaveStatus.APPROVED)
        flash(request, f"{len(pending)} leave request(s) were approved.", "success")

    @action(
        name="reject",
        text="Reject selected leave requests",
        confirmation="Reject the selected leave requests? Requests that "
        "aren't pending are left untouched.",
        submit_btn_text="Yes, reject",
        submit_btn_class="btn-outline-danger",
        icon_class="fa-solid fa-xmark",
    )
    async def reject_action(self, request: Request, selection: ActionSelection) -> None:
        leave_requests = await selection.rows()
        pending = [lr for lr in leave_requests if lr.status == LeaveStatus.PENDING]
        self._review(request, pending, LeaveStatus.REJECTED)
        flash(request, f"{len(pending)} leave request(s) were rejected.", "success")

    def _review(
        self, request: Request, leave_requests: list[LeaveRequest], status: LeaveStatus
    ) -> None:
        session: Session = request.state.session
        now = datetime.utcnow()
        for leave_request in leave_requests:
            leave_request.status = status
            leave_request.reviewed_at = now
            session.add(leave_request)
        session.flush()  # the session is committed automatically at the end of each request
        if leave_requests:
            on_commit(request, trigger_dashboard_refresh)
        for leave_request in leave_requests:
            log_action(
                request,
                self.key,
                leave_request.id,
                f"{status.value.title()} leave request for "
                f"{leave_request.employee.name}",
            )


# ── Project (soft-deletable) ─────────────────────────────────────────────────


class ExpenseLineInline(InlineModelView):
    model = ExpenseLine
    fields = [
        "id",
        StringField(
            "description",
            required=True,
            validators=[length(max=300)],
        ),
        DecimalField(
            "amount",
            required=True,
            validators=[number_range(min=0, max=1_000_000)],
        ),
        IntegerField(
            "quantity",
            validators=[number_range(min=1, max=100)],
        ),
        DecimalField(
            "unit_price",
            required=True,
            validators=[number_range(min=0, max=10_000)],
        ),
        "date",
    ]
    menu_label = "Expense lines"
    collapsed = True


class TaskInline(InlineModelView):
    model = Task
    fk_attr = "project_id"
    fields = [
        "id",
        StringField(
            "title",
            required=True,
            validators=[length(max=200)],
        ),
        TaskStatusBadgeField("status", enum=TaskStatus),
        TaskPriorityBadgeField("priority", enum=TaskPriority),
        "assignee",
        "due_date",
    ]
    menu_label = "Tasks"


class ProjectView(SoftDeleteModelView):
    """Detail page is `templates/project/detail.html`, a mini dashboard with three stat cards (budget burn, task breakdown, timeline) in place of the stock attribute table.

    The template gets this view as `view` and the model as `raw_obj`, rendering e.g. `view.budget_burn(raw_obj)` per the methods below.
    """

    detail_template = "project/detail.html"

    fields = [
        "id",
        StringField(
            "name",
            required=True,
            validators=[length(max=200)],
        ),
        SlugField(
            "slug",
            populate_from="name",
            required=True,
            validators=[
                slug(),
                unique(
                    Project,
                    Project.slug,
                    message="A project with this slug already exists.",
                ),
            ],
        ),
        TextAreaField(
            "description",
            validators=[length(max=2000)],
        ),
        ProjectStatusBadgeField("status", enum=ProjectStatus),
        TaskPriorityBadgeField("priority", enum=TaskPriority),
        DollarField(
            "budget",
            help_text="Total budget allocated to the project, in USD.",
            validators=[number_range(min=0, max=1_000_000_000)],
        ),
        DollarField(
            "spent",
            help_text="Total amount spent on the project, in USD.",
            validators=[number_range(min=0, max=1_000_000_000)],
        ),
        DecimalField(
            "estimated_hours",
            validators=[number_range(min=0, max=9_999_999.9)],
        ),
        DecimalField(
            "actual_hours",
            validators=[number_range(min=0, max=9_999_999.9)],
        ),
        ProgressField(
            "progress", help_text="Actual hours logged as a share of estimated hours."
        ),
        "start_date",
        "end_date",
        "plan",
        "department",
        "deleted_at",
    ]
    exclude_fields_from_list = [
        *SoftDeleteModelView.exclude_fields_from_list,
        "id",
        "slug",
        "description",
        "plan",
        "estimated_hours",
        "actual_hours",
    ]
    inlines = [TaskInline]
    fields_default_sort = ["name"]
    # search_vector also covers list-excluded slug/description and folds in the department's name.
    searchable_fields = [
        "name",
        "status",
        "priority",
        "budget",
        "spent",
        "start_date",
        "end_date",
        "department",
    ]
    sortable_fields = [
        "name",
        "status",
        "priority",
        "budget",
        "spent",
        "start_date",
        "end_date",
    ]
    # Quick edits from the list page, without opening the full form.
    inline_editable_fields = ["status", "priority"]
    form_layout = [
        FieldsetWidget(
            legend="Identity",
            children=[("name", "slug"), "description", "department"],
        ),
        PanelWidget(
            title="Status",
            children=[("status", "priority"), ("start_date", "end_date")],
        ),
        PanelWidget(
            title="Budget & Effort",
            children=[
                TextWidget(
                    content="Actuals feed the burn and timeline cards on the "
                    "detail dashboard.",
                    card=False,
                ),
                (FieldRef("budget", prepend="$"), FieldRef("spent", prepend="$")),
                (
                    FieldRef("estimated_hours", append="hrs"),
                    FieldRef("actual_hours", append="hrs"),
                ),
            ],
            collapsible=True,
            collapsed=True,
        ),
    ]

    async def validate(self, request: Request, data: dict[str, Any]) -> None:
        # Cross-field only: budget and spent each have their own field validator (see the `budget`/`spent` fields above).
        errors: dict[str, str] = {}
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        if start_date is not None and end_date is not None and end_date < start_date:
            errors["end_date"] = "End date must be on or after the start date."
        if errors:
            raise FormValidationError(errors)
        await super().validate(request, data)

    # Reused for its color/icon mappings, so the breakdown card matches the task list and inline table's badges.
    _task_status_badges = TaskStatusBadgeField("status", enum=TaskStatus)

    @staticmethod
    def budget_burn(obj: Any) -> dict[str, Any]:
        """Share of `budget` consumed by `spent`, as progress bar context; turns orange at 80%, red past 100%."""
        if not obj.budget:
            return {"width": 0, "bar_class": "bg-secondary", "label": "No budget set"}
        percent = round(float(obj.spent) / float(obj.budget) * 100)
        bar_class = (
            "bg-danger"
            if percent > 100
            else "bg-warning"
            if percent >= 80
            else "bg-primary"
        )
        return {
            "width": min(percent, 100),
            "bar_class": bar_class,
            "label": f"{percent}% of budget spent",
        }

    def task_stats(self, obj: Any) -> list[dict[str, Any]]:
        """Task counts by status, shaped for `fields/badge.html`.

        Omits empty statuses; iterates `TaskStatus` so order follows the workflow, not insertion order.
        """
        counts = Counter(task.status for task in obj.tasks)
        return [
            {
                "label": status.value.replace("_", " ").title(),
                "badge_class": self._task_status_badges.badge_class_by_value.get(
                    status.value, "badge"
                ),
                "icon": self._task_status_badges.icon_by_value.get(status.value),
                "count": counts[status],
            }
            for status in TaskStatus
            if counts[status]
        ]

    @staticmethod
    def timeline(obj: Any) -> dict[str, Any]:
        """Headline (days left/overdue/status) plus progress bar context for where `obj` sits between `start_date` and `end_date`."""
        today = date.today()
        if obj.status == ProjectStatus.COMPLETED:
            return {"headline": "Completed", "width": 100, "bar_class": "bg-success"}
        if today < obj.start_date:
            days = (obj.start_date - today).days
            return {
                "headline": f"Starts in {days} day{'s' if days != 1 else ''}",
                "width": 0,
                "bar_class": "bg-primary",
            }
        if obj.end_date is None:
            day = (today - obj.start_date).days + 1
            return {"headline": f"Day {day}", "width": 0, "bar_class": "bg-primary"}
        remaining = (obj.end_date - today).days
        if remaining < 0:
            return {
                "headline": f"{-remaining} day{'s' if remaining != -1 else ''} overdue",
                "width": 100,
                "bar_class": "bg-danger",
            }
        total = max((obj.end_date - obj.start_date).days, 1)
        elapsed = (today - obj.start_date).days
        return {
            "headline": f"{remaining} day{'s' if remaining != 1 else ''} left",
            "width": min(round(elapsed / total * 100), 100),
            "bar_class": "bg-primary",
        }


# ── Task ─────────────────────────────────────────────────────────────────────


class TaskView(ModelView):
    fields = [
        "id",
        StringField(
            "title",
            required=True,
            validators=[length(max=200)],
        ),
        TextAreaField(
            "description",
            validators=[length(max=2000)],
        ),
        HasOne("project", key="project", required=True),
        "assignee",
        TaskStatusBadgeField("status", enum=TaskStatus),
        TaskPriorityBadgeField("priority", enum=TaskPriority),
        DecimalField(
            "estimated_hours",
            validators=[number_range(min=0, max=99_999.9)],
        ),
        DecimalField(
            "actual_hours",
            validators=[number_range(min=0, max=99_999.9)],
        ),
        "due_date",
        "completed_at",
        "labels",
    ]
    exclude_fields_from_list = ["id", "description", "labels"]
    # search_vector also covers list-excluded description and folds in the project's and assignee's names.
    searchable_fields = [
        "title",
        "status",
        "priority",
        "estimated_hours",
        "actual_hours",
        "due_date",
        "completed_at",
        "project",
        "assignee",
    ]
    sortable_fields = [
        "title",
        "status",
        "priority",
        "due_date",
        "completed_at",
        "estimated_hours",
        "actual_hours",
    ]
    # Quick edits from the list page, without opening the full form.
    inline_editable_fields = ["status", "priority"]
    form_layout = [
        FieldsetWidget(
            legend="Details",
            children=["title", "description", ("project", "assignee")],
        ),
        PanelWidget(
            title="Status & Priority",
            children=[("status", "priority"), ("due_date", "completed_at")],
        ),
        PanelWidget(
            title="Effort",
            children=[
                (
                    FieldRef("estimated_hours", append="hrs"),
                    FieldRef("actual_hours", append="hrs"),
                ),
                "labels",
            ],
            collapsible=True,
            collapsed=True,
        ),
    ]


# ── Timesheet ────────────────────────────────────────────────────────────────


class TimesheetView(ModelView):
    fields = [
        "id",
        HasOne("employee", key="employee", required=True),
        "date",
        DecimalField(
            "hours",
            required=True,
            validators=[
                number_gt(0),
                number_range(max=999.9),
            ],
        ),
        IntegerField(
            "minutes",
            validators=[number_range(min=0, max=59)],
        ),
        TextAreaField(
            "description",
            validators=[length(max=1000)],
        ),
        "is_billable",
        DecimalField(
            "hourly_rate",
            validators=[number_range(min=0, max=999_999.99)],
        ),
        DecimalField(
            "total_cost",
            validators=[number_range(min=0, max=99_999_999.99)],
        ),
        "task",
        HasOne("project", key="project", required=True),
    ]
    exclude_fields_from_list = ["id", "project"]
    fields_default_sort = [("date", True)]
    # search_vector also covers description and folds in the employee, task and project names.
    searchable_fields = [
        "date",
        "hours",
        "is_billable",
        "hourly_rate",
        "total_cost",
        "employee",
        "task",
        "project",
    ]
    sortable_fields = ["date", "hours", "is_billable", "hourly_rate", "total_cost"]
    # Quick edits from the list page, without opening the full form.
    inline_editable_fields = ["is_billable"]
    form_layout = [
        FieldsetWidget(
            legend="Entry",
            children=[("employee", "project"), ("task", "date"), "description"],
        ),
        PanelWidget(
            title="Time & Billing",
            children=[
                (
                    FieldRef("hours", append="hrs"),
                    FieldRef("minutes", append="min"),
                ),
                ("is_billable", FieldRef("hourly_rate", prepend="$")),
                FieldRef("total_cost", prepend="$"),
            ],
        ),
    ]
    search_auto_submit = False


# ── Expense ──────────────────────────────────────────────────────────────────


class ExpenseView(ModelView):
    fields = [
        "id",
        HasOne("employee", key="employee", required=True),
        "project",
        StringField(
            "expense_number",
            required=True,
            validators=[
                length(max=40),
                unique(
                    Expense,
                    Expense.expense_number,
                    message="An expense with this number already exists.",
                ),
            ],
        ),
        ExpenseStatusBadgeField("status", enum=ExpenseStatus),
        ExpenseCategoryBadgeField("category", enum=ExpenseCategory, required=True),
        TextAreaField(
            "description",
            required=True,
            validators=[length(max=2000)],
        ),
        DollarField(
            "total_amount",
            help_text="Sum of this expense's line items, in USD. Derived, not editable.",
            read_only=True,
        ),
        "submitted_at",
        "approved_at",
        "approved_by",
        StringField(
            "receipt_path",
            validators=[length(max=500)],
        ),
        TextAreaField(
            "notes",
            validators=[length(max=2000)],
        ),
    ]
    exclude_fields_from_list = ["id", "description", "notes", "receipt_path"]
    exclude_fields_from_create = ["total_amount"]
    inlines = [ExpenseLineInline]
    fields_default_sort = [("submitted_at", True)]
    # search_vector also covers list-excluded description/notes and folds in the employee, project and approver names.
    searchable_fields = [
        "expense_number",
        "status",
        "category",
        "total_amount",
        "submitted_at",
        "approved_at",
        "employee",
        "project",
        "approved_by",
    ]
    sortable_fields = [
        "expense_number",
        "status",
        "category",
        "total_amount",
        "submitted_at",
        "approved_at",
    ]
    # Quick edits from the list page, without opening the full form.
    inline_editable_fields = ["status"]
    form_layout = [
        FieldsetWidget(
            legend="Details",
            children=[("employee", "project"), "expense_number", "description"],
        ),
        PanelWidget(title="Classification", children=[("status", "category")]),
        PanelWidget(
            title="Approval",
            children=[
                TextWidget(
                    content="Set by the review workflow rather than entered by hand.",
                    card=False,
                ),
                ("submitted_at", "approved_at"),
                ("approved_by", FieldRef("total_amount", prepend="$")),
            ],
            collapsible=True,
            collapsed=True,
        ),
        PanelWidget(
            title="Receipt & Notes",
            children=["receipt_path", "notes"],
            collapsible=True,
            collapsed=True,
        ),
    ]

    async def validate(self, request: Request, data: dict[str, Any]) -> None:
        errors: dict[str, str] = {}
        submitted_at = data.get("submitted_at")
        approved_at = data.get("approved_at")
        if (
            submitted_at is not None
            and approved_at is not None
            and approved_at < submitted_at
        ):
            errors["approved_at"] = "Approval time cannot precede submission time."
        if data.get("status") == ExpenseStatus.APPROVED and not data.get("approved_by"):
            errors["approved_by"] = "An approver is required for an approved expense."
        if errors:
            raise FormValidationError(errors)
        await super().validate(request, data)

    async def after_create_committed(self, request: Request, obj: Any) -> None:
        await self._recompute_total_amount(request, obj.id)

    async def after_edit_committed(self, request: Request, obj: Any) -> None:
        await self._recompute_total_amount(request, obj.id)

    @staticmethod
    async def _recompute_total_amount(request: Request, expense_id: int) -> None:
        """Set `total_amount` to the sum of this expense's line items.

        Runs after commit, once inline `ExpenseLine` rows are guaranteed saved, so it opens its own session rather than `request.state.session`, already closed by this point.
        """
        engine = request.state.session.get_bind()

        def _update() -> None:
            with Session(engine) as session:
                total = session.scalar(
                    select(func.coalesce(func.sum(ExpenseLine.amount), 0)).where(
                        ExpenseLine.expense_id == expense_id
                    )
                )
                session.execute(
                    update(Expense)
                    .where(Expense.id == expense_id)
                    .values(total_amount=total)
                )
                session.commit()

        await anyio.to_thread.run_sync(_update)
