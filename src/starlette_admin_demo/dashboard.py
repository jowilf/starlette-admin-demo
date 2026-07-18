"""Dashboard index view. `HRDashboardView` replaces the admin's default index with
stock widgets plus one custom widget, `OrgChartWidget`, which renders the department
hierarchy with ApexTree - a reference for writing your own: subclass `BaseWidget`,
point `template` at a file under `templates_dir`, return context from `get_context`,
and declare vendor scripts in `additional_js_links`.

Every number here is a plain Redis read via a `stats.py` callback (see cache.py), never
a live query, so a page load never blocks on the database.
"""

from calendar import monthrange
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar
from uuid import uuid4

from starlette.requests import Request
from starlette_admin import (
    Breakpoints,
    CardRowWidget,
    ChartWidget,
    Col,
    ColumnWidget,
    CustomView,
    GridWidget,
    HtmlWidget,
    PanelWidget,
    StatWidget,
    TableWidget,
    TabsWidget,
    TextWidget,
)
from starlette_admin.widgets import BaseWidget

from . import stats
from .models import (
    EmploymentType,
    ExpenseCategory,
    ExpenseStatus,
    LeaveStatus,
    LeaveType,
    ProjectStatus,
    TaskPriority,
    TaskStatus,
)
from .stats import _fmt_money, _last_months, _title

# Pinned to 1.3.0: last release without a license gate (no watermark). The
# API used here is stable across 1.x, so upgrading needs a license key only.
APEXTREE_JS = "https://cdn.jsdelivr.net/npm/apextree@1.3.0/apextree.min.js"

# Colorblind-safe categorical palette; order is fixed (assigned to series in this order).
CATEGORICAL = [
    "#2a78d6",
    "#1baf7a",
    "#eda100",
    "#008300",
    "#4a3aa7",
    "#e34948",
    "#e87ba4",
    "#eb6834",
]

# Mirrors the Tabler badge semantics used in the list views (green=good, amber=waiting, red=rejected).
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"
NEUTRAL = "#9ca3af"
INFO = "#2a78d6"
ACCENT = "#4a3aa7"

LEAVE_STATUS_COLORS = {
    LeaveStatus.PENDING: WARNING,
    LeaveStatus.APPROVED: GOOD,
    LeaveStatus.REJECTED: CRITICAL,
    LeaveStatus.TAKEN: INFO,
    LeaveStatus.CANCELLED: NEUTRAL,
}

PROJECT_STATUS_COLORS = {
    ProjectStatus.PLANNING: NEUTRAL,
    ProjectStatus.ACTIVE: GOOD,
    ProjectStatus.ON_HOLD: WARNING,
    ProjectStatus.COMPLETED: INFO,
    ProjectStatus.CANCELLED: CRITICAL,
}

TASK_STATUS_COLORS = {
    TaskStatus.BACKLOG: NEUTRAL,
    TaskStatus.TODO: INFO,
    TaskStatus.IN_PROGRESS: WARNING,
    TaskStatus.IN_REVIEW: ACCENT,
    TaskStatus.COMPLETED: GOOD,
    TaskStatus.CANCELLED: CRITICAL,
}

TASK_PRIORITY_COLORS = {
    TaskPriority.LOW: NEUTRAL,
    TaskPriority.MEDIUM: INFO,
    TaskPriority.HIGH: WARNING,
    TaskPriority.CRITICAL: CRITICAL,
}

EXPENSE_STATUS_COLORS = {
    ExpenseStatus.DRAFT: NEUTRAL,
    ExpenseStatus.SUBMITTED: WARNING,
    ExpenseStatus.APPROVED: GOOD,
    ExpenseStatus.REJECTED: CRITICAL,
    ExpenseStatus.REIMBURSED: INFO,
}


# ── Custom widget: ApexTree organization chart ───────────────────────────────


@dataclass
class OrgChartWidget(BaseWidget):
    """Renders a hierarchy as an interactive ApexTree organization chart. Data source
    agnostic: `tree_callback` returns the nested node structure ApexTree consumes, each
    node needing `id`, `children`, and a `data` payload (`name`, `people`, `budget`, `color`)."""

    template: ClassVar[str] = "widgets/org_chart_widget.html"

    title: str
    tree_callback: Callable[[Request], Awaitable[dict[str, Any]]]
    height: int = 620
    direction: str = "top"
    node_width: int = 176
    node_height: int = 76

    def additional_js_links(self, request: Request) -> list[str]:
        return [APEXTREE_JS]

    async def get_context(self, request: Request) -> dict[str, Any]:
        tree = await self.tree_callback(request)
        return {
            "widget": self,
            "title": self.title,
            "chart_id": f"org-chart-{uuid4().hex[:8]}",
            "tree": tree,
            "height": self.height,
            "direction": self.direction,
            "node_width": self.node_width,
            "node_height": self.node_height,
        }


# ── Dashboard view ───────────────────────────────────────────────────────────


class HRDashboardView(CustomView):
    """Admin index page: KPI cards, the org chart, and tabbed analytics.

    The widget tree is rebuilt on every request (`widget` is a callable),
    so headline descriptions can be computed from the same cached values
    that feed the charts.
    """

    def __init__(self) -> None:
        super().__init__(
            menu_label="Dashboard",
            icon="fa fa-gauge-high",
            path="/",
            add_to_menu=True,
            widget=self._build_widget,
        )

    async def _build_widget(self, request: Request) -> ColumnWidget:
        today = date.today()
        month_start = today.replace(day=1)
        month_end = today.replace(day=monthrange(today.year, today.month)[1])

        hires = await stats.hires_sparkline(request)
        hire_counts = hires[0]["data"]
        hiring_up = len(hire_counts) >= 2 and hire_counts[-1] >= hire_counts[-2]

        total_projects = await stats.total_projects(request)
        pending_expense_total = await stats.pending_expense_total(request)
        salaried = await stats.salaried_count(request)
        billable_this_month = await stats.billable_hours_this_month(request)

        month_labels = [label for _, label in _last_months(12)]
        division_names = await stats.division_names(request)

        def stat_col(widget: StatWidget) -> Col:
            return Col(widget, breakpoints=Breakpoints(default=12, md=6, lg=3))

        return ColumnWidget(
            children=[
                TextWidget(
                    content=(
                        "## HR Overview\n\n"
                        "Snapshot of the workforce, projects, time tracking, "
                        "and spend, cached in Redis and refreshed the moment "
                        "something underneath it changes; follow a card to "
                        "drill into the underlying records."
                    ),
                    markdown=True,
                    card=True,
                ),
                HtmlWidget(
                    html=(
                        '<div class="alert alert-info d-flex align-items-center gap-2" role="alert">'
                        '<i class="fa-solid fa-circle-info"></i>'
                        "<span>Quick links: "
                        f'<a href="{request.url_for("admin:list", key="employee")}">Employees</a> &middot; '
                        f'<a href="{request.url_for("admin:list", key="project")}">Projects</a> &middot; '
                        f'<a href="{request.url_for("admin:list", key="leave-request")}">Leave requests</a> &middot; '
                        f'<a href="{request.url_for("admin:list", key="expense")}">Expenses</a>'
                        "</span></div>"
                    )
                ),
                CardRowWidget(
                    children=[
                        stat_col(
                            StatWidget(
                                title="Employees",
                                value_callback=stats.count_employees,
                                chart_type="area",
                                chart_callback=stats.hires_sparkline,
                                description=(
                                    "Hiring is up this month"
                                    if hiring_up
                                    else "Hiring slowed this month"
                                ),
                                description_icon=(
                                    "fa-solid fa-arrow-trend-up"
                                    if hiring_up
                                    else "fa-solid fa-arrow-trend-down"
                                ),
                                color="success" if hiring_up else "warning",
                                link=request.url_for("admin:list", key="employee"),
                                countup=True,
                            )
                        ),
                        stat_col(
                            StatWidget(
                                title="Active Projects",
                                value_callback=stats.count_active_projects,
                                description=f"of {total_projects} projects overall",
                                description_icon="fa-solid fa-diagram-project",
                                color="primary",
                                link=request.url_for(
                                    "admin:list", key="project"
                                ).include_query_params(filter="status__eq=active"),
                                countup=True,
                            )
                        ),
                        stat_col(
                            StatWidget(
                                title="Pending Leave",
                                value_callback=stats.count_pending_leave,
                                description="requests awaiting review",
                                description_icon="fa-solid fa-hourglass-half",
                                color="warning",
                                link=request.url_for(
                                    "admin:list", key="leave-request"
                                ).include_query_params(filter="status__eq=pending"),
                                countup=True,
                            )
                        ),
                        stat_col(
                            StatWidget(
                                title="Open Tasks",
                                value_callback=stats.count_open_tasks,
                                description="in backlog, progress, or review",
                                description_icon="fa-solid fa-list-check",
                                color="info",
                                link=request.url_for(
                                    "admin:list", key="task"
                                ).include_query_params(
                                    filter="status__in=backlog,todo,in_progress,in_review"
                                ),
                                countup=True,
                            )
                        ),
                    ]
                ),
                CardRowWidget(
                    children=[
                        stat_col(
                            StatWidget(
                                title="Annual Payroll",
                                value_callback=stats.annual_payroll,
                                description=f"across {salaried} salaried employees",
                                description_icon="fa-solid fa-money-check-dollar",
                                color="primary",
                            )
                        ),
                        stat_col(
                            StatWidget(
                                title="Hours This Month",
                                value_callback=stats.hours_this_month,
                                chart_type="area",
                                chart_callback=stats.hours_sparkline,
                                description=f"{billable_this_month:.0f}h billable",
                                description_icon="fa-solid fa-clock",
                                color="success",
                                link=request.url_for(
                                    "admin:list", key="timesheet"
                                ).include_query_params(
                                    filter=f"date__between={month_start.isoformat()}..{month_end.isoformat()}"
                                ),
                            )
                        ),
                        stat_col(
                            StatWidget(
                                title="Expenses To Review",
                                value_callback=stats.count_submitted_expenses,
                                description=f"{_fmt_money(pending_expense_total)} awaiting approval",
                                description_icon="fa-solid fa-receipt",
                                color="warning",
                                link=request.url_for(
                                    "admin:list", key="expense"
                                ).include_query_params(filter="status__eq=submitted"),
                                countup=True,
                            )
                        ),
                        stat_col(
                            StatWidget(
                                title="Departments",
                                value_callback=stats.count_departments,
                                description=f"{len(division_names)} top level divisions",
                                description_icon="fa-solid fa-sitemap",
                                color="secondary",
                                link=request.url_for(
                                    "admin:list", key="department"
                                ).include_query_params(filter="is_active__is_true"),
                                countup=True,
                            )
                        ),
                    ]
                ),
                # Stays outside the tabs: a hidden tab pane measures 0, and
                # ApexTree measures its container at render time.
                OrgChartWidget(
                    title="Organization Chart",
                    tree_callback=stats.org_tree,
                    height=440,
                ),
                TabsWidget(
                    tabs=[
                        ("Workforce", self._workforce_tab(request, division_names)),
                        (
                            "Projects & Tasks",
                            self._projects_tab(request, division_names),
                        ),
                        ("Time & Money", self._money_tab(request, month_labels)),
                    ]
                ),
            ]
        )

    # ── tab builders ─────────────────────────────────────────────────────────

    def _workforce_tab(
        self, request: Request, division_names: list[str]
    ) -> ColumnWidget:
        year_labels = [str(date.today().year - offset) for offset in range(9, -1, -1)]
        return ColumnWidget(
            children=[
                CardRowWidget(
                    children=[
                        Col(
                            ChartWidget(
                                title="Headcount by Division",
                                chart_type="bar",
                                series_callback=stats.headcount_by_division,
                                options={
                                    "colors": [CATEGORICAL[0]],
                                    "plotOptions": {"bar": {"horizontal": True}},
                                    "xaxis": {"categories": division_names},
                                },
                            ),
                            breakpoints=Breakpoints(default=12, lg=7),
                        ),
                        Col(
                            ChartWidget(
                                title="Employment Type Mix",
                                chart_type="donut",
                                series_callback=stats.employment_type_series,
                                options={
                                    "labels": [_title(t.value) for t in EmploymentType],
                                    "colors": CATEGORICAL[: len(EmploymentType)],
                                },
                            ),
                            breakpoints=Breakpoints(default=12, lg=5),
                        ),
                    ]
                ),
                CardRowWidget(
                    children=[
                        Col(
                            ChartWidget(
                                title="Hires per Year",
                                chart_type="area",
                                series_callback=stats.hires_per_year,
                                options={
                                    "colors": [CATEGORICAL[0]],
                                    "xaxis": {"categories": year_labels},
                                    "dataLabels": {"enabled": False},
                                },
                            ),
                            breakpoints=Breakpoints(default=12, lg=6),
                        ),
                        Col(
                            ChartWidget(
                                title="Leave Requests by Type and Status",
                                chart_type="bar",
                                series_callback=stats.leave_stacked_series,
                                options={
                                    "chart": {"stacked": True},
                                    "colors": [
                                        LEAVE_STATUS_COLORS[s] for s in LeaveStatus
                                    ],
                                    "xaxis": {
                                        "categories": [
                                            _title(t.value) for t in LeaveType
                                        ]
                                    },
                                    "dataLabels": {"enabled": False},
                                },
                            ),
                            breakpoints=Breakpoints(default=12, lg=6),
                        ),
                    ]
                ),
                PanelWidget(
                    title="People Movements",
                    icon="fa-solid fa-person-walking-arrow-right",
                    children=[
                        CardRowWidget(
                            children=[
                                Col(
                                    TableWidget(
                                        title="Recent Hires",
                                        columns=[
                                            "Name",
                                            "Job Title",
                                            "Department",
                                            "Hired",
                                        ],
                                        rows_callback=stats.recent_hires,
                                    ),
                                    breakpoints=Breakpoints(default=12, lg=6),
                                ),
                                Col(
                                    TableWidget(
                                        title="Upcoming Leave",
                                        columns=[
                                            "Employee",
                                            "Type",
                                            "Status",
                                            "Starts",
                                            "Days",
                                        ],
                                        rows_callback=stats.upcoming_leave,
                                    ),
                                    breakpoints=Breakpoints(default=12, lg=6),
                                ),
                            ]
                        )
                    ],
                ),
            ]
        )

    def _projects_tab(
        self, request: Request, division_names: list[str]
    ) -> ColumnWidget:
        return ColumnWidget(
            children=[
                GridWidget(
                    breakpoints=Breakpoints(default=1, md=2, lg=3),
                    gutter=4,
                    children=[
                        ChartWidget(
                            title="Projects by Status",
                            chart_type="donut",
                            series_callback=stats.projects_by_status,
                            options={
                                "labels": [_title(s.value) for s in ProjectStatus],
                                "colors": [
                                    PROJECT_STATUS_COLORS[s] for s in ProjectStatus
                                ],
                            },
                        ),
                        ChartWidget(
                            title="Tasks by Status",
                            chart_type="bar",
                            series_callback=stats.tasks_by_status,
                            options={
                                "colors": [TASK_STATUS_COLORS[s] for s in TaskStatus],
                                "plotOptions": {"bar": {"distributed": True}},
                                "legend": {"show": False},
                                "xaxis": {
                                    "categories": [_title(s.value) for s in TaskStatus]
                                },
                            },
                        ),
                        ChartWidget(
                            title="Tasks by Priority",
                            chart_type="bar",
                            series_callback=stats.tasks_by_priority,
                            options={
                                "colors": [
                                    TASK_PRIORITY_COLORS[p] for p in TaskPriority
                                ],
                                "plotOptions": {"bar": {"distributed": True}},
                                "legend": {"show": False},
                                "xaxis": {
                                    "categories": [
                                        _title(p.value) for p in TaskPriority
                                    ]
                                },
                            },
                        ),
                    ],
                ),
                ChartWidget(
                    title="Project Budget vs Spend by Division ($K)",
                    chart_type="bar",
                    series_callback=stats.budget_by_division,
                    height=320,
                    options={
                        "colors": [CATEGORICAL[0], CATEGORICAL[1]],
                        "xaxis": {"categories": division_names},
                        "dataLabels": {"enabled": False},
                    },
                ),
                PanelWidget(
                    title="Delivery Watchlist",
                    icon="fa-solid fa-triangle-exclamation",
                    children=[
                        CardRowWidget(
                            children=[
                                Col(
                                    TableWidget(
                                        title="Largest Project Budgets",
                                        columns=[
                                            "Project",
                                            "Department",
                                            "Budget",
                                            "Spent",
                                            "Burn",
                                        ],
                                        rows_callback=stats.top_projects,
                                    ),
                                    breakpoints=Breakpoints(default=12, lg=6),
                                ),
                                Col(
                                    TableWidget(
                                        title="Overdue Tasks",
                                        columns=[
                                            "Task",
                                            "Project",
                                            "Assignee",
                                            "Due",
                                            "Priority",
                                        ],
                                        rows_callback=stats.overdue_tasks,
                                    ),
                                    breakpoints=Breakpoints(default=12, lg=6),
                                ),
                            ]
                        )
                    ],
                ),
            ]
        )

    def _money_tab(self, request: Request, month_labels: list[str]) -> ColumnWidget:
        return ColumnWidget(
            children=[
                CardRowWidget(
                    children=[
                        Col(
                            ChartWidget(
                                title="Hours Logged per Month",
                                chart_type="line",
                                series_callback=stats.hours_per_month,
                                options={
                                    "colors": [CATEGORICAL[0], CATEGORICAL[2]],
                                    "xaxis": {"categories": month_labels},
                                    "stroke": {"width": 2},
                                    "dataLabels": {"enabled": False},
                                },
                            ),
                            breakpoints=Breakpoints(default=12, lg=8),
                        ),
                        Col(
                            ChartWidget(
                                title="Billable Share (last 12 months)",
                                chart_type="radialBar",
                                series_callback=stats.billable_share,
                                options={
                                    "labels": ["Billable"],
                                    "colors": [GOOD],
                                },
                            ),
                            breakpoints=Breakpoints(default=12, lg=4),
                        ),
                    ]
                ),
                CardRowWidget(
                    children=[
                        Col(
                            ChartWidget(
                                title="Expense Amounts by Category",
                                chart_type="donut",
                                series_callback=stats.expenses_by_category,
                                options={
                                    "labels": [
                                        _title(c.value) for c in ExpenseCategory
                                    ],
                                    "colors": CATEGORICAL[: len(ExpenseCategory)],
                                },
                            ),
                            breakpoints=Breakpoints(default=12, lg=6),
                        ),
                        Col(
                            ChartWidget(
                                title="Expense Amounts by Status",
                                chart_type="bar",
                                series_callback=stats.expenses_by_status,
                                options={
                                    "colors": [
                                        EXPENSE_STATUS_COLORS[s] for s in ExpenseStatus
                                    ],
                                    "plotOptions": {"bar": {"distributed": True}},
                                    "legend": {"show": False},
                                    "xaxis": {
                                        "categories": [
                                            _title(s.value) for s in ExpenseStatus
                                        ]
                                    },
                                    "dataLabels": {"enabled": False},
                                },
                            ),
                            breakpoints=Breakpoints(default=12, lg=6),
                        ),
                    ]
                ),
                TableWidget(
                    title="Expenses Awaiting Approval",
                    columns=["Number", "Employee", "Category", "Amount", "Submitted"],
                    rows_callback=stats.pending_expenses,
                ),
            ]
        )
