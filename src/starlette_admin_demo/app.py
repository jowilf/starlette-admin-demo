"""07-hr: an HR admin, ported from the Filament demo's HR module
(filamentphp/demo, app/Models/HR)."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette_admin import DropDown
from starlette_admin.contrib.sqla import Admin
from starlette_admin.export import ExportConfig
from starlette_admin.i18n import SUPPORTED_LOCALES, I18nConfig, TimezoneConfig
from starlette_admin.importers import ImportConfig
from starlette_admin.logging import configure_logging

from .audit import AuditLog, AuditLogView, AuditSubscriber
from .auth import MyAuthProvider
from .cache import (
    DashboardCacheSubscriber,
    dashboard_cache_lifespan,
    trigger_dashboard_refresh,
)
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
    # Creates tables only; seeding is handled separately by seed.py.
    Base.metadata.create_all(engine)
    # Kick off one immediate cache refresh so the dashboard isn't empty until Celery Beat's first tick (see cache.py).
    trigger_dashboard_refresh()
    async with dashboard_cache_lifespan():
        yield


app = FastAPI(lifespan=lifespan)

admin = Admin(
    engine,
    base_url="/",
    title="Example: HR",
    secret_key=SECRET_KEY,
    templates_dir="templates",
    static_dir="static",
    logo_url="/static/logo.svg",
    login_logo_url="/static/login_logo.svg",
    index_view=HRDashboardView(),
    auth_provider=MyAuthProvider(),
    # Deliberately strict, low limits so the "capacity exceeded" errors are easy to demo.
    import_config=ImportConfig(max_upload_size=20 * 1024, max_rows=10),
    export_config=ExportConfig(max_rows=10),
    i18n_config=I18nConfig(language_switcher=SUPPORTED_LOCALES),
    timezone_config=TimezoneConfig(
        timezone_switcher=[
            "UTC",
            "Europe/Paris",
            "Europe/Berlin",
            "Europe/London",
            "Africa/Porto-Novo",
            "America/New_York",
            "America/Los_Angeles",
            "Asia/Tokyo",
            "Asia/Shanghai",
            "Australia/Sydney",
        ],
    ),
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
# Triggers an out-of-band dashboard cache refresh on the same events (see cache.py).
admin.events.subscribe(DashboardCacheSubscriber())

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

admin.mount_to(app)

configure_logging(level=logging.ERROR)
