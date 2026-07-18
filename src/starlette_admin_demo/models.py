"""SQLAlchemy models for the HR module, ported from the Filament HR demo
(filamentphp/demo, app/Models/HR). `SoftDeleteMixin` marks a model as hide-on-delete
(Employee, Project, pair with `SoftDeleteModelView` in views.py); every table also
carries a `search_vector` column and index, backed by the trigger infrastructure in search.py.
"""

import enum
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from starlette.requests import Request


class Base(DeclarativeBase):
    """Base class for every SQLAlchemy declarative model in the HR example."""


# Deferred past `Base`: search.py imports `Base` back from this still-executing
# module, which only resolves once `Base` already exists as an attribute here.
from .search import search_vector_column, search_vector_index  # noqa: E402


class SoftDeleteMixin:
    """Adds `deleted_at`: NULL means live, any other value means deleted through the
    admin. Pair with `SoftDeleteModelView` (views.py) so list/count queries hide
    trashed rows and delete stamps this instead of running DELETE."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None, index=True
    )


# ── Enums ────────────────────────────────────────────────────────────────────
# Values mirror the Filament demo's PHP backed enums (App\Enums\*).


class EmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACTOR = "contractor"
    INTERN = "intern"


class LeaveType(str, enum.Enum):
    ANNUAL = "annual"
    SICK = "sick"
    PERSONAL = "personal"
    UNPAID = "unpaid"
    PARENTAL = "parental"


class LeaveStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TAKEN = "taken"
    CANCELLED = "cancelled"


class ProjectStatus(str, enum.Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(str, enum.Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ExpenseCategory(str, enum.Enum):
    TRAVEL = "travel"
    MEALS = "meals"
    SUPPLIES = "supplies"
    EQUIPMENT = "equipment"
    SOFTWARE = "software"
    OTHER = "other"


class ExpenseStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    REIMBURSED = "reimbursed"


# ── Department ───────────────────────────────────────────────────────────────


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (search_vector_index("departments"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("departments.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    budget: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, index=True)
    headcount: Mapped[int] = mapped_column(Integer, default=0, index=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    search_vector: Mapped[str | None] = search_vector_column()

    parent: Mapped["Department | None"] = relationship(
        "Department", remote_side=[id], back_populates="children"
    )
    children: Mapped[list["Department"]] = relationship(
        "Department", back_populates="parent"
    )
    employees: Mapped[list["Employee"]] = relationship(
        "Employee", back_populates="department"
    )
    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="department"
    )

    async def __admin_repr__(self, request: Request) -> str:
        return self.name


# ── Employee ─────────────────────────────────────────────────────────────────


class Employee(SoftDeleteMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (
        # `deleted_at IS NULL` alone doesn't narrow anything (matches virtually every
        # row); these composites earn their keep by making the dashboard's aggregates
        # covering (index-only) instead of a table lookup per matched row.
        Index("ix_employees_deleted_at_hire_date", "deleted_at", "hire_date", "salary"),
        Index(
            "ix_employees_deleted_at_employment_type", "deleted_at", "employment_type"
        ),
        Index("ix_employees_deleted_at_department_id", "deleted_at", "department_id"),
        search_vector_index("employees"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    avatar: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    job_title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    employment_type: Mapped[EmploymentType] = mapped_column(
        Enum(EmploymentType),
        default=EmploymentType.FULL_TIME,
        nullable=False,
        index=True,
    )
    salary: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True, index=True
    )
    skills: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    search_vector: Mapped[str | None] = search_vector_column()

    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("departments.id"), nullable=True, index=True
    )
    department: Mapped["Department | None"] = relationship(
        "Department", back_populates="employees"
    )
    leave_requests: Mapped[list["LeaveRequest"]] = relationship(
        "LeaveRequest",
        back_populates="employee",
        foreign_keys="LeaveRequest.employee_id",
    )
    approved_leave_requests: Mapped[list["LeaveRequest"]] = relationship(
        "LeaveRequest",
        back_populates="approver",
        foreign_keys="LeaveRequest.approver_id",
    )
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="assignee")
    timesheets: Mapped[list["Timesheet"]] = relationship(
        "Timesheet", back_populates="employee"
    )
    expenses: Mapped[list["Expense"]] = relationship(
        "Expense", back_populates="employee", foreign_keys="Expense.employee_id"
    )
    approved_expenses: Mapped[list["Expense"]] = relationship(
        "Expense", back_populates="approved_by", foreign_keys="Expense.approved_by_id"
    )

    async def __admin_repr__(self, request: Request) -> str:
        return self.name


# ── LeaveRequest ─────────────────────────────────────────────────────────────


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        # Covers the upcoming-leave table widget: filters on status and
        # ranges/sorts on start_date.
        Index("ix_leave_requests_status_start_date", "status", "start_date"),
        # Covers the leave-by-type-and-status chart: unfiltered COUNT(*)
        # grouped by (status, type) - a covering index-only scan.
        Index("ix_leave_requests_status_type", "status", "type"),
        search_vector_index("leave_requests"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("employees.id"), nullable=False, index=True
    )
    approver_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id"), nullable=True, index=True
    )
    type: Mapped[LeaveType] = mapped_column(Enum(LeaveType), nullable=False, index=True)
    status: Mapped[LeaveStatus] = mapped_column(
        Enum(LeaveStatus), default=LeaveStatus.PENDING, nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    days_requested: Mapped[Decimal] = mapped_column(
        Numeric(4, 1), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    search_vector: Mapped[str | None] = search_vector_column()

    employee: Mapped["Employee"] = relationship(
        "Employee", back_populates="leave_requests", foreign_keys=[employee_id]
    )
    approver: Mapped["Employee | None"] = relationship(
        "Employee",
        back_populates="approved_leave_requests",
        foreign_keys=[approver_id],
    )

    async def __admin_repr__(self, request: Request) -> str:
        return f"{self.employee.name}: {self.type.value} ({self.start_date} → {self.end_date})"


# ── Project ──────────────────────────────────────────────────────────────────


class Project(SoftDeleteMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (search_vector_index("projects"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("departments.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus), default=ProjectStatus.PLANNING, nullable=False, index=True
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority), default=TaskPriority.MEDIUM, nullable=False, index=True
    )
    budget: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, index=True)
    spent: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, index=True)
    estimated_hours: Mapped[Decimal] = mapped_column(Numeric(8, 1), default=0)
    actual_hours: Mapped[Decimal] = mapped_column(Numeric(8, 1), default=0)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    search_vector: Mapped[str | None] = search_vector_column()

    department: Mapped["Department | None"] = relationship(
        "Department", back_populates="projects"
    )
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="project")
    timesheets: Mapped[list["Timesheet"]] = relationship(
        "Timesheet", back_populates="project"
    )
    expenses: Mapped[list["Expense"]] = relationship(
        "Expense", back_populates="project"
    )

    async def __admin_repr__(self, request: Request) -> str:
        return self.name


# ── Task ─────────────────────────────────────────────────────────────────────


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        # Covers the overdue-tasks table widget. due_date leads: the NOT IN on
        # status excludes only 2 of 6 values, too unselective to lead the index.
        Index("ix_tasks_due_date_status", "due_date", "status"),
        search_vector_index("tasks"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False, index=True
    )
    assigned_to: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.BACKLOG, nullable=False, index=True
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority), default=TaskPriority.MEDIUM, nullable=False, index=True
    )
    estimated_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 1), nullable=True, index=True
    )
    actual_hours: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    labels: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    search_vector: Mapped[str | None] = search_vector_column()

    project: Mapped["Project"] = relationship("Project", back_populates="tasks")
    assignee: Mapped["Employee | None"] = relationship(
        "Employee", back_populates="tasks", foreign_keys=[assigned_to]
    )
    timesheets: Mapped[list["Timesheet"]] = relationship(
        "Timesheet", back_populates="task"
    )

    async def __admin_repr__(self, request: Request) -> str:
        return self.title


# ── Timesheet ────────────────────────────────────────────────────────────────


class Timesheet(Base):
    __tablename__ = "timesheets"
    __table_args__ = (
        # Covers hours-per-month/billable-share charts (ranges on date, groups on
        # is_billable, sums hours); hours rides along so the scan stays index-only.
        Index("ix_timesheets_date_is_billable", "date", "is_billable", "hours"),
        search_vector_index("timesheets"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("employees.id"), nullable=False, index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tasks.id"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, index=True)
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    is_billable: Mapped[bool] = mapped_column(default=True)
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, index=True)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, index=True)
    search_vector: Mapped[str | None] = search_vector_column()

    employee: Mapped["Employee"] = relationship("Employee", back_populates="timesheets")
    task: Mapped["Task | None"] = relationship("Task", back_populates="timesheets")
    project: Mapped["Project"] = relationship("Project", back_populates="timesheets")

    async def __admin_repr__(self, request: Request) -> str:
        return f"{self.employee.name} — {self.date} ({self.hours}h)"


# ── Expense / ExpenseLine ────────────────────────────────────────────────────


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        # Covers the pending-expenses table widget (filters on status, sorts
        # on submitted_at) and the amounts-by-status chart (unfiltered SUM
        # of total_amount grouped by status) as a covering scan.
        Index(
            "ix_expenses_status_submitted_at", "status", "submitted_at", "total_amount"
        ),
        # Covers the amounts-by-category chart: unfiltered SUM(total_amount)
        # grouped by category, as a covering scan.
        Index("ix_expenses_category_total_amount", "category", "total_amount"),
        search_vector_index("expenses"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("employees.id"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=True, index=True
    )
    expense_number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    status: Mapped[ExpenseStatus] = mapped_column(
        Enum(ExpenseStatus), default=ExpenseStatus.DRAFT, nullable=False
    )
    category: Mapped[ExpenseCategory] = mapped_column(
        Enum(ExpenseCategory), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    approved_by_id: Mapped[int | None] = mapped_column(
        "approved_by", Integer, ForeignKey("employees.id"), nullable=True, index=True
    )
    receipt_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    # Hyphenated numbers like EXP-2024-0001 tokenize into searchable parts
    # (exp, 2024, 0001) as well as the whole token.
    search_vector: Mapped[str | None] = search_vector_column()

    employee: Mapped["Employee"] = relationship(
        "Employee", back_populates="expenses", foreign_keys=[employee_id]
    )
    project: Mapped["Project | None"] = relationship(
        "Project", back_populates="expenses"
    )
    approved_by: Mapped["Employee | None"] = relationship(
        "Employee",
        back_populates="approved_expenses",
        foreign_keys=[approved_by_id],
    )
    expense_lines: Mapped[list["ExpenseLine"]] = relationship(
        "ExpenseLine", back_populates="expense", cascade="all, delete-orphan"
    )

    async def __admin_repr__(self, request: Request) -> str:
        return self.expense_number


class ExpenseLine(Base):
    __tablename__ = "expense_lines"
    __table_args__ = (search_vector_index("expense_lines"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expense_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("expenses.id"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    search_vector: Mapped[str | None] = search_vector_column()

    expense: Mapped["Expense"] = relationship("Expense", back_populates="expense_lines")

    async def __admin_repr__(self, request: Request) -> str:
        return f"{self.description} x{self.quantity}"
