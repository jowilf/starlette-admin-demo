"""Dashboard query functions (see `dashboard.py`). Each is decorated with
`@precomputed_stat` (see cache.py), which registers the undecorated `async def
foo(session)` for a Celery task to run into Redis, and rebinds the module-level name
to a read-only `async def foo(request)` wrapper - a plain Redis read, never a query -
which is what `dashboard.py` actually calls.
"""

from calendar import monthrange
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .cache import precomputed_stat
from .config import engine
from .models import (
    Department,
    Employee,
    EmploymentType,
    Expense,
    ExpenseCategory,
    ExpenseStatus,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Project,
    ProjectStatus,
    Task,
    TaskPriority,
    TaskStatus,
    Timesheet,
)

# ── formatting / date helpers ────────────────────────────────────────────────


def _title(value: str) -> str:
    """Human readable label for an enum value, e.g. "in_progress" -> "In Progress"."""
    return value.replace("_", " ").title()


def _fmt_money(value: Any) -> str:
    """Compact dollar amount for cards and org chart nodes, e.g. "$1.2M"."""
    amount = float(value or 0)
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:.0f}"


_TO_CHAR_FORMATS = {"%Y-%m": "YYYY-MM", "%Y": "YYYY"}


def _sql_date_format(fmt: str, column: Any) -> Any:
    """Format a date column with `%Y`/`%m` specifiers, dialect-agnostic:
    SQLite's `strftime(fmt, col)` vs PostgreSQL's `to_char(col, fmt)`."""
    if engine.dialect.name == "postgresql":
        return func.to_char(column, _TO_CHAR_FORMATS[fmt])
    return func.strftime(fmt, column)


def _month_key(value: date) -> str:
    """Inverse of `_month_key_to_date`: a plain `date` back to its
    "YYYY-MM" key, matching `_sql_date_format('%Y-%m', ...)` output."""
    return f"{value.year:04d}-{value.month:02d}"


def _month_key_to_date(key: str) -> date:
    """First-of-month `date` for a `_sql_date_format('%Y-%m', ...)` key like
    "2026-03". Used to turn a month-key cutoff into a plain date comparison
    so WHERE clauses stay sargable (indexable) instead of wrapping the
    column in a date-formatting function."""
    return date.fromisoformat(f"{key}-01")


def _last_months(count: int) -> list[tuple[str, str]]:
    """Last `count` calendar months, oldest first, as (key, label) pairs;
    `key` matches `_sql_date_format('%Y-%m', ...)` output."""
    year, month = date.today().year, date.today().month
    months: list[tuple[str, str]] = []
    for _ in range(count):
        months.append(
            (f"{year:04d}-{month:02d}", date(year, month, 1).strftime("%b %y"))
        )
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    months.reverse()
    return months


# ── stat callbacks ───────────────────────────────────────────────────────────


@precomputed_stat("count_employees", default=0)
async def count_employees(session: Session) -> int:
    return (
        session.scalar(
            select(func.count(Employee.id)).where(Employee.deleted_at.is_(None))
        )
        or 0
    )


@precomputed_stat("count_active_projects", default=0)
async def count_active_projects(session: Session) -> int:
    return (
        session.scalar(
            select(func.count(Project.id)).where(
                Project.deleted_at.is_(None),
                Project.status == ProjectStatus.ACTIVE,
            )
        )
        or 0
    )


@precomputed_stat("count_pending_leave", default=0)
async def count_pending_leave(session: Session) -> int:
    return (
        session.scalar(
            select(func.count(LeaveRequest.id)).where(
                LeaveRequest.status == LeaveStatus.PENDING
            )
        )
        or 0
    )


@precomputed_stat("count_open_tasks", default=0)
async def count_open_tasks(session: Session) -> int:
    return (
        session.scalar(
            select(func.count(Task.id)).where(
                Task.status.not_in([TaskStatus.COMPLETED, TaskStatus.CANCELLED])
            )
        )
        or 0
    )


@precomputed_stat("annual_payroll", default="$0")
async def annual_payroll(session: Session) -> str:
    total = session.scalar(
        select(func.coalesce(func.sum(Employee.salary), 0)).where(
            Employee.deleted_at.is_(None)
        )
    )
    return _fmt_money(total)


@precomputed_stat("hours_this_month", default="0h")
async def hours_this_month(session: Session) -> str:
    today = date.today()
    month_start = today.replace(day=1)
    month_end = today.replace(day=monthrange(today.year, today.month)[1])
    total = session.scalar(
        select(func.coalesce(func.sum(Timesheet.hours), 0)).where(
            Timesheet.date.between(month_start, month_end)
        )
    )
    return f"{total:.0f}h"


@precomputed_stat("count_submitted_expenses", default=0)
async def count_submitted_expenses(session: Session) -> int:
    return (
        session.scalar(
            select(func.count(Expense.id)).where(
                Expense.status == ExpenseStatus.SUBMITTED
            )
        )
        or 0
    )


@precomputed_stat("count_departments", default=0)
async def count_departments(session: Session) -> int:
    return (
        session.scalar(
            select(func.count(Department.id)).where(Department.is_active.is_(True))
        )
        or 0
    )


@precomputed_stat("total_projects", default=0)
async def total_projects(session: Session) -> int:
    return (
        session.scalar(
            select(func.count(Project.id)).where(Project.deleted_at.is_(None))
        )
        or 0
    )


@precomputed_stat("pending_expense_total", default=0.0)
async def pending_expense_total(session: Session) -> float:
    total = session.scalar(
        select(func.coalesce(func.sum(Expense.total_amount), 0)).where(
            Expense.status == ExpenseStatus.SUBMITTED
        )
    )
    return float(total or 0)


@precomputed_stat("salaried_count", default=0)
async def salaried_count(session: Session) -> int:
    return (
        session.scalar(
            select(func.count(Employee.id)).where(
                Employee.deleted_at.is_(None), Employee.salary.is_not(None)
            )
        )
        or 0
    )


@precomputed_stat("billable_hours_this_month", default=0.0)
async def billable_hours_this_month(session: Session) -> float:
    today = date.today()
    month_start = today.replace(day=1)
    month_end = today.replace(day=monthrange(today.year, today.month)[1])
    total = session.scalar(
        select(func.coalesce(func.sum(Timesheet.hours), 0)).where(
            Timesheet.date.between(month_start, month_end),
            Timesheet.is_billable.is_(True),
        )
    )
    return float(total or 0)


# ── sparkline callbacks ──────────────────────────────────────────────────────


@precomputed_stat("hires_sparkline", default=[{"name": "Hires", "data": [0] * 12}])
async def hires_sparkline(session: Session) -> list[dict[str, Any]]:
    months = _last_months(12)
    cutoff = _month_key_to_date(months[0][0])
    month_expr = _sql_date_format("%Y-%m", Employee.hire_date)
    counts = dict(
        session.execute(
            select(month_expr, func.count(Employee.id))
            .where(
                Employee.deleted_at.is_(None),
                Employee.hire_date >= cutoff,
            )
            .group_by(month_expr)
        ).all()
    )
    return [{"name": "Hires", "data": [counts.get(key, 0) for key, _ in months]}]


@precomputed_stat("hours_sparkline", default=[{"name": "Hours", "data": [0] * 12}])
async def hours_sparkline(session: Session) -> list[dict[str, Any]]:
    months = _last_months(12)
    cutoff = _month_key_to_date(months[0][0])
    # Group by the raw (indexed) date, not a month-formatting expression, so the DB
    # can stream in index order instead of sorting the whole range; bucket into months here.
    rows = session.execute(
        select(Timesheet.date, func.sum(Timesheet.hours))
        .where(Timesheet.date >= cutoff)
        .group_by(Timesheet.date)
    ).all()
    totals: dict[str, float] = {}
    for day, hours in rows:
        key = _month_key(day)
        totals[key] = totals.get(key, 0.0) + float(hours or 0)
    return [
        {
            "name": "Hours",
            "data": [totals.get(key, 0.0) for key, _ in months],
        }
    ]


# ── chart callbacks ──────────────────────────────────────────────────────────


def _division_names_query(session: Session) -> list[str]:
    """Top level division names (the root's direct children), by id order. A plain
    helper, not `@precomputed_stat`-decorated: the decorated `division_names` would hit
    its Redis-reading wrapper instead of running the query if called from here."""
    root_id = session.scalar(
        select(Department.id).where(Department.parent_id.is_(None))
    )
    return list(
        session.scalars(
            select(Department.name)
            .where(Department.parent_id == root_id)
            .order_by(Department.id)
        )
    )


@precomputed_stat("division_names", default=[])
async def division_names(session: Session) -> list[str]:
    return _division_names_query(session)


def _division_of(session: Session) -> dict[int, str]:
    """Map every department id to the name of its top level division. The root
    department maps to itself, so rows attached directly to it still land in a bucket."""
    rows = session.execute(
        select(Department.id, Department.name, Department.parent_id)
    ).all()
    by_id = {dep_id: (name, parent_id) for dep_id, name, parent_id in rows}

    def climb(dep_id: int) -> str:
        name, parent_id = by_id[dep_id]
        # Stop one level below the root; the root maps to itself.
        while parent_id is not None and by_id[parent_id][1] is not None:
            name, parent_id = by_id[parent_id]
        return name

    return {dep_id: climb(dep_id) for dep_id in by_id}


def _employee_headcounts(session: Session) -> dict[int, int]:
    """Live employee count per `department_id`, cached on the session so a single
    `refresh_all` pass only runs this aggregate once even though multiple stats need it."""
    cached = session.info.get("employee_headcounts")
    if cached is None:
        cached = dict(
            session.execute(
                select(Employee.department_id, func.count(Employee.id))
                .where(
                    Employee.deleted_at.is_(None),
                    Employee.department_id.is_not(None),
                )
                .group_by(Employee.department_id)
            ).all()
        )
        session.info["employee_headcounts"] = cached
    return cached


@precomputed_stat("headcount_by_division", default=[{"name": "Employees", "data": []}])
async def headcount_by_division(session: Session) -> list[dict[str, Any]]:
    division_of = _division_of(session)
    totals: dict[str, int] = dict.fromkeys(_division_names_query(session), 0)
    rows = _employee_headcounts(session).items()
    for department_id, count in rows:
        division = division_of.get(department_id)
        if division in totals:
            totals[division] += count
    return [{"name": "Employees", "data": list(totals.values())}]


@precomputed_stat("employment_type_series", default=[0] * len(EmploymentType))
async def employment_type_series(session: Session) -> list[int]:
    counts = dict(
        session.execute(
            select(Employee.employment_type, func.count(Employee.id))
            .where(Employee.deleted_at.is_(None))
            .group_by(Employee.employment_type)
        ).all()
    )
    return [counts.get(employment_type, 0) for employment_type in EmploymentType]


@precomputed_stat("hires_per_year", default=[{"name": "Hires", "data": [0] * 10}])
async def hires_per_year(session: Session) -> list[dict[str, Any]]:
    year_expr = _sql_date_format("%Y", Employee.hire_date)
    counts = dict(
        session.execute(
            select(year_expr, func.count(Employee.id))
            .where(Employee.deleted_at.is_(None))
            .group_by(year_expr)
        ).all()
    )
    years = [str(date.today().year - offset) for offset in range(9, -1, -1)]
    return [{"name": "Hires", "data": [counts.get(year, 0) for year in years]}]


@precomputed_stat(
    "leave_stacked_series",
    default=[
        {"name": _title(s.value), "data": [0] * len(LeaveType)} for s in LeaveStatus
    ],
)
async def leave_stacked_series(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            LeaveRequest.status,
            LeaveRequest.type,
            func.count(LeaveRequest.id),
        ).group_by(LeaveRequest.status, LeaveRequest.type)
    ).all()
    counts: dict[tuple[LeaveStatus, LeaveType], int] = {
        (status, leave_type): count for status, leave_type, count in rows
    }
    return [
        {
            "name": _title(status.value),
            "data": [counts.get((status, leave_type), 0) for leave_type in LeaveType],
        }
        for status in LeaveStatus
    ]


@precomputed_stat("projects_by_status", default=[0] * len(ProjectStatus))
async def projects_by_status(session: Session) -> list[int]:
    counts = dict(
        session.execute(
            select(Project.status, func.count(Project.id))
            .where(Project.deleted_at.is_(None))
            .group_by(Project.status)
        ).all()
    )
    return [counts.get(status, 0) for status in ProjectStatus]


@precomputed_stat(
    "tasks_by_status", default=[{"name": "Tasks", "data": [0] * len(TaskStatus)}]
)
async def tasks_by_status(session: Session) -> list[dict[str, Any]]:
    counts = dict(
        session.execute(
            select(Task.status, func.count(Task.id)).group_by(Task.status)
        ).all()
    )
    return [{"name": "Tasks", "data": [counts.get(status, 0) for status in TaskStatus]}]


@precomputed_stat(
    "tasks_by_priority", default=[{"name": "Tasks", "data": [0] * len(TaskPriority)}]
)
async def tasks_by_priority(session: Session) -> list[dict[str, Any]]:
    counts = dict(
        session.execute(
            select(Task.priority, func.count(Task.id)).group_by(Task.priority)
        ).all()
    )
    return [
        {
            "name": "Tasks",
            "data": [counts.get(priority, 0) for priority in TaskPriority],
        }
    ]


@precomputed_stat(
    "budget_by_division",
    default=[{"name": "Budget", "data": []}, {"name": "Spent", "data": []}],
)
async def budget_by_division(session: Session) -> list[dict[str, Any]]:
    division_of = _division_of(session)
    divisions = _division_names_query(session)
    budget: dict[str, float] = dict.fromkeys(divisions, 0.0)
    spent: dict[str, float] = dict.fromkeys(divisions, 0.0)
    rows = session.execute(
        select(
            Project.department_id,
            func.sum(Project.budget),
            func.sum(Project.spent),
        )
        .where(Project.deleted_at.is_(None), Project.department_id.is_not(None))
        .group_by(Project.department_id)
    ).all()
    for department_id, budget_sum, spent_sum in rows:
        division = division_of.get(department_id)
        if division in budget:
            budget[division] += float(budget_sum or 0)
            spent[division] += float(spent_sum or 0)
    return [
        # Reported in thousands of dollars to keep axis labels short.
        {"name": "Budget", "data": [round(budget[d] / 1000) for d in divisions]},
        {"name": "Spent", "data": [round(spent[d] / 1000) for d in divisions]},
    ]


@precomputed_stat(
    "hours_per_month",
    default=[
        {"name": "Billable", "data": [0] * 12},
        {"name": "Non-billable", "data": [0] * 12},
    ],
)
async def hours_per_month(session: Session) -> list[dict[str, Any]]:
    months = _last_months(12)
    cutoff = _month_key_to_date(months[0][0])
    # Grouping by the raw date (and is_billable) matches the covering
    # index's column order exactly, so the DB can stream sums without
    # sorting; bucket the ~366 resulting rows into months here instead.
    rows = session.execute(
        select(Timesheet.date, Timesheet.is_billable, func.sum(Timesheet.hours))
        .where(Timesheet.date >= cutoff)
        .group_by(Timesheet.date, Timesheet.is_billable)
    ).all()
    totals: dict[tuple[str, bool], float] = {}
    for day, billable, hours in rows:
        key = (_month_key(day), bool(billable))
        totals[key] = totals.get(key, 0.0) + float(hours or 0)
    return [
        {
            "name": "Billable",
            "data": [totals.get((key, True), 0.0) for key, _ in months],
        },
        {
            "name": "Non-billable",
            "data": [totals.get((key, False), 0.0) for key, _ in months],
        },
    ]


@precomputed_stat("billable_share", default=[0.0])
async def billable_share(session: Session) -> list[float]:
    months = _last_months(12)
    cutoff = _month_key_to_date(months[0][0])
    total = session.scalar(
        select(func.coalesce(func.sum(Timesheet.hours), 0)).where(
            Timesheet.date >= cutoff
        )
    )
    billable = session.scalar(
        select(func.coalesce(func.sum(Timesheet.hours), 0)).where(
            Timesheet.date >= cutoff, Timesheet.is_billable.is_(True)
        )
    )
    if not total:
        return [0.0]
    return [round(float(billable) / float(total) * 100, 1)]


@precomputed_stat("expenses_by_category", default=[0.0] * len(ExpenseCategory))
async def expenses_by_category(session: Session) -> list[float]:
    totals = dict(
        session.execute(
            select(Expense.category, func.sum(Expense.total_amount)).group_by(
                Expense.category
            )
        ).all()
    )
    return [
        round(float(totals.get(category, 0) or 0), 2) for category in ExpenseCategory
    ]


@precomputed_stat(
    "expenses_by_status",
    default=[{"name": "Amount", "data": [0] * len(ExpenseStatus)}],
)
async def expenses_by_status(session: Session) -> list[dict[str, Any]]:
    totals = dict(
        session.execute(
            select(Expense.status, func.sum(Expense.total_amount)).group_by(
                Expense.status
            )
        ).all()
    )
    return [
        {
            "name": "Amount",
            "data": [
                round(float(totals.get(status, 0) or 0)) for status in ExpenseStatus
            ],
        }
    ]


# ── table callbacks ──────────────────────────────────────────────────────────


@precomputed_stat("recent_hires", default=[])
async def recent_hires(session: Session) -> list[list[Any]]:
    employees = session.scalars(
        select(Employee)
        .where(Employee.deleted_at.is_(None))
        .order_by(Employee.hire_date.desc())
        .limit(6)
        .options(selectinload(Employee.department))
    ).all()
    return [
        [
            employee.name,
            employee.job_title,
            employee.department.name if employee.department else "Unassigned",
            employee.hire_date.strftime("%Y-%m-%d"),
        ]
        for employee in employees
    ]


@precomputed_stat("upcoming_leave", default=[])
async def upcoming_leave(session: Session) -> list[list[Any]]:
    leave_requests = session.scalars(
        select(LeaveRequest)
        .where(
            LeaveRequest.start_date >= date.today(),
            LeaveRequest.status.in_([LeaveStatus.APPROVED, LeaveStatus.PENDING]),
        )
        .order_by(LeaveRequest.start_date.asc())
        .limit(6)
        .options(selectinload(LeaveRequest.employee))
    ).all()
    return [
        [
            leave.employee.name,
            _title(leave.type.value),
            _title(leave.status.value),
            leave.start_date.strftime("%Y-%m-%d"),
            f"{leave.days_requested:g}",
        ]
        for leave in leave_requests
    ]


@precomputed_stat("top_projects", default=[])
async def top_projects(session: Session) -> list[list[Any]]:
    projects = session.scalars(
        select(Project)
        .where(Project.deleted_at.is_(None))
        .order_by(Project.budget.desc())
        .limit(6)
        .options(selectinload(Project.department))
    ).all()
    return [
        [
            project.name,
            project.department.name if project.department else "Unassigned",
            _fmt_money(project.budget),
            _fmt_money(project.spent),
            f"{float(project.spent) / float(project.budget) * 100:.0f}%"
            if project.budget
            else "n/a",
        ]
        for project in projects
    ]


@precomputed_stat("overdue_tasks", default=[])
async def overdue_tasks(session: Session) -> list[list[Any]]:
    tasks = session.scalars(
        select(Task)
        .where(
            Task.due_date < date.today(),
            Task.status.not_in([TaskStatus.COMPLETED, TaskStatus.CANCELLED]),
        )
        .order_by(Task.due_date.asc())
        .limit(6)
        .options(selectinload(Task.project), selectinload(Task.assignee))
    ).all()
    return [
        [
            task.title,
            task.project.name,
            task.assignee.name if task.assignee else "Unassigned",
            task.due_date.strftime("%Y-%m-%d"),
            _title(task.priority.value),
        ]
        for task in tasks
    ]


@precomputed_stat("pending_expenses", default=[])
async def pending_expenses(session: Session) -> list[list[Any]]:
    expenses = session.scalars(
        select(Expense)
        .where(Expense.status == ExpenseStatus.SUBMITTED)
        .order_by(Expense.submitted_at.desc())
        .limit(6)
        .options(selectinload(Expense.employee))
    ).all()
    return [
        [
            expense.expense_number,
            expense.employee.name,
            _title(expense.category.value),
            f"${expense.total_amount:,.2f}",
            expense.submitted_at.strftime("%Y-%m-%d") if expense.submitted_at else "",
        ]
        for expense in expenses
    ]


# ── org chart callback ───────────────────────────────────────────────────────


@precomputed_stat(
    "org_tree",
    default={"id": "empty", "data": {"name": "No departments"}, "children": []},
)
async def org_tree(session: Session) -> dict[str, Any]:
    """Nested department tree in the shape ApexTree renders: each node
    shows name, headcount (self + descendants), budget, and the
    department's stored color as card background."""
    departments = session.scalars(select(Department).order_by(Department.id)).all()
    head_counts = _employee_headcounts(session)
    children_of: dict[int | None, list[Department]] = {}
    for department in departments:
        children_of.setdefault(department.parent_id, []).append(department)

    def build(department: Department) -> tuple[dict[str, Any], int]:
        child_nodes: list[dict[str, Any]] = []
        people = head_counts.get(department.id, 0)
        for child in children_of.get(department.id, []):
            node, subtree_people = build(child)
            child_nodes.append(node)
            people += subtree_people
        color = department.color or "#6b7280"
        return {
            "id": str(department.id),
            "data": {
                "name": department.name,
                "people": f"{people} {'person' if people == 1 else 'people'}",
                "budget": _fmt_money(department.budget),
                "color": color,
            },
            "options": {"nodeBGColor": color, "nodeBGColorHover": color},
            "children": child_nodes,
        }, people

    roots = children_of.get(None, [])
    if not roots:
        return {"id": "empty", "data": {"name": "No departments"}, "children": []}
    root_node, _ = build(roots[0])
    return root_node
