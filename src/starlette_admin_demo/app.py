"""
07-hr: an HR admin, ported from the Filament demo's HR module
(filamentphp/demo, app/Models/HR).

Department -> Employee -> {LeaveRequest, Task, Timesheet, Expense} -> Project,
with Employee and Project soft-deletable through the shared
`SoftDeleteMixin` / `SoftDeleteModelView` pair defined in models.py / views.py.

Timesheet and LeaveRequest are grouped under a single "Time & Attendance"
dropdown in the menu.
"""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette_admin import DropDown
from starlette_admin.contrib.sqla import Admin
from starlette_admin.export import ExportConfig
from starlette_admin.importers import ImportConfig
from starlette_admin.logging import configure_logging

from .audit import AuditLog, AuditLogView, AuditSubscriber
from .auth import MyAuthProvider
from .config import SECRET_KEY, UMAMI_HOST, UMAMI_WEBSITE_ID, engine
from .dashboard import HRDashboardView
from .models import (
    Base,
    Department,
    Employee,
    Expense,
    LeaveRequest,
    Project,
    Task,
    Timesheet,
)
from .views import (
    DepartmentView,
    EmployeeView,
    ExpenseView,
    LeaveRequestView,
    ProjectView,
    TaskView,
    TimesheetView,
)


@asynccontextmanager
async def lifespan(_: Starlette):
    # Tables are created here, but data is not: seeding is handled by the
    # standalone seed.py script, which populates a running app through the
    # admin's own HTTP endpoints. See seed.py for usage.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(lifespan=lifespan)

admin = Admin(
    engine,
    base_url="/",
    title="Example: HR",
    secret_key=SECRET_KEY,
    templates_dir="templates",
    # The dashboard replaces the default index page; see dashboard.py.
    index_view=HRDashboardView(),
    auth_provider=MyAuthProvider(),
    # Deliberately strict, low limits to make the "capacity exceeded"
    # errors easy to trigger and demo.
    import_config=ImportConfig(max_upload_size=1 * 1024, max_rows=10),  # 1 KB
    export_config=ExportConfig(max_rows=10),
)

# Consumed by templates/base.html to inject the Umami tracking script.
admin.templates.env.globals["umami_host"] = UMAMI_HOST
admin.templates.env.globals["umami_website_id"] = UMAMI_WEBSITE_ID

admin.add_view(DepartmentView(Department, icon="fa fa-sitemap"))
admin.add_view(EmployeeView(Employee, icon="fa fa-id-badge"))
admin.add_view(ProjectView(Project, icon="fa fa-diagram-project"))
admin.add_view(TaskView(Task, icon="fa fa-list-check"))
admin.add_view(ExpenseView(Expense, icon="fa fa-receipt"))
admin.add_view(
    DropDown(
        "Time & Attendance",
        icon="fa fa-business-time",
        views=[
            TimesheetView(Timesheet, icon="fa fa-clock"),
            LeaveRequestView(LeaveRequest, icon="fa fa-calendar-days"),
        ],
    )
)
admin.add_view(AuditLogView(AuditLog, icon="fa fa-clipboard-list"))

# Writes an AuditLog row for create/edit/delete/export/import on every view above.
admin.events.subscribe(AuditSubscriber())

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

admin.mount_to(app)

configure_logging(level=logging.ERROR)
