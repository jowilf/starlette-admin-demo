"""Seed the 07-hr example through the running admin's own HTTP endpoints.

Unlike `seed.py` (which writes straight to the database through SQLAlchemy),
this script drives the same data through `app.py`'s actual create/edit forms
over HTTP, exactly as a browser would. That means going through login and
`starlette_admin`'s CSRF protection on every mutating request.

CSRF, concretely (see `starlette_admin.security.csrf.CSRFMiddleware`):
it's a signed double-submit cookie. A `GET` response sets a signed
`starlette_admin_csrftoken` cookie; any mutating request (`POST`) must echo
that same signed value back via an `X-CSRFToken` header (or a `csrftoken`
form field). So every write below follows the same two-step shape: `GET`
the page first (establishes/confirms the cookie), then `POST` with the
cookie's value copied into the `X-CSRFToken` header. See
`AdminApiClient._request` for the one place that pattern lives.

New rows don't come back with their id in the response body (a create POST
redirects to the list page). Instead, this submits the framework's own
`_continue_editing` form field alongside every create, which redirects to
`/{key}/edit?pk=<new pk>` instead -- the pk is then just read off the
`Location` header (see `AdminApiClient.create`).

Employees and projects are soft-deletable (`SoftDeleteMixin` /
`SoftDeleteModelView`, see models.py / views.py): once a row is soft-deleted,
`SoftDeleteModelView.get_detail_query` hides it, and any later create that
tries to reference it as a relation (e.g. a task's assignee) would fail to
resolve. So, unlike seed.py, the soft-delete pass here runs last, after
every entity that might reference an employee or project already exists.

Usage:
    uv run seed_api.py                       # against http://127.0.0.1:8000
    uv run seed_api.py --base-url http://localhost:8000 --scale 0.2
    uv run seed_api.py --no-reset             # append instead of wiping first

The target app must already be running. Schema reset (`--reset`, the
default) still goes straight through SQLAlchemy first, same as seed.py:
there is no admin endpoint for wiping the database, so that one step isn't
"through the API" -- every row after it is.
"""

import argparse
import random
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from config import avatars_storage
from config import engine as app_engine
from faker import Faker
from models import Base
from seed import (
    EMPLOYMENT_TYPES,
    EXPENSE_CATEGORIES,
    EXPENSE_STATUSES,
    LEAVE_STATUSES,
    LEAVE_TYPES,
    ORG_CHART,
    PRIORITIES,
    PROJECT_STATUSES,
    SKILLS,
    TASK_LABELS,
    TASK_STATUSES,
    SeedConfig,
    pick,
    pick_department,
    scaled_counts,
    slugify,
)

ASSETS_DIR = Path(__file__).parent / "assets"
AVATAR_UPLOAD_FOLDER = "avatars"

CSRF_COOKIE_NAME = "starlette_admin_csrftoken"
CSRF_HEADER_NAME = "X-CSRFToken"


# ── HTTP client ──────────────────────────────────────────────────────────────


class AdminApiClient:
    """Talks to the running admin the same way a logged-in browser would."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.http = httpx.Client(
            base_url=base_url, follow_redirects=False, timeout=30.0
        )
        self._login(username, password)

    def _csrf_headers(self) -> dict[str, str]:
        token = self.http.cookies.get(CSRF_COOKIE_NAME)
        return {CSRF_HEADER_NAME: token} if token else {}

    def _login(self, username: str, password: str) -> None:
        self.http.get("/login")  # GET first: this is what sets the csrf cookie
        response = self.http.post(
            "/login",
            data={"username": username, "password": password},
            headers=self._csrf_headers(),
        )
        if response.status_code != 303:
            raise RuntimeError(
                f"login failed: {response.status_code} {response.text[:300]}"
            )

    def create(
        self, key: str, data: dict[str, Any], files: dict[str, Any] | None = None
    ) -> str:
        """POST a new row to `/{key}/create`, and return its new pk.

        Submitting `_continue_editing` makes the framework redirect to
        `/{key}/edit?pk=<new pk>` instead of the list page, so the pk can be
        read straight off the `Location` header.
        """
        self.http.get(f"/{key}/create")
        response = self.http.post(
            f"/{key}/create",
            data={**data, "_continue_editing": "1"},
            files=files,
            headers=self._csrf_headers(),
        )
        if response.status_code != 303:
            raise RuntimeError(
                f"create {key} failed: {response.status_code} {response.text[:500]}"
            )
        query = parse_qs(urlsplit(response.headers["location"]).query)
        return query["pk"][0]

    def edit(self, key: str, pk: str, data: dict[str, Any]) -> None:
        """POST the full field set for an existing row to `/{key}/edit?pk=`.

        Unlike a PATCH, this replaces every field the view exposes, so
        callers must resend the complete payload (see the department
        headcount backfill in `seed_via_api`), not just the changed field.
        """
        self.http.get(f"/{key}/edit", params={"pk": pk})
        response = self.http.post(
            f"/{key}/edit",
            params={"pk": pk},
            data=data,
            headers=self._csrf_headers(),
        )
        if response.status_code != 303:
            raise RuntimeError(
                f"edit {key}#{pk} failed: {response.status_code} {response.text[:500]}"
            )

    def bulk_action(self, key: str, name: str, pks: list[str]) -> None:
        """POST a batch action (e.g. the built-in "delete") for a list of pks."""
        self.http.get(f"/{key}/list")
        response = self.http.post(
            f"/_api/{key}/action",
            params=[("name", name), *[("pks", pk) for pk in pks]],
            headers=self._csrf_headers(),
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"action {name} on {key} failed: "
                f"{response.status_code} {response.text[:500]}"
            )


def _to_form_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return "on" if value else None  # unchecked checkboxes just aren't sent
    if isinstance(value, dict):
        import json

        return json.dumps(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [str(v) for v in value]
    return str(value)


def clean(data: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw payload dict to the strings starlette_admin's form
    fields expect, dropping keys whose value is None (omitted, rather than
    submitted empty, so optional relations/dates parse to None -- see e.g.
    `RelationField.parse_form_data` and `DateField.parse_form_data`)."""
    cleaned = {k: _to_form_value(v) for k, v in data.items()}
    return {k: v for k, v in cleaned.items() if v is not None}


# ── Record builders (payload dicts, not ORM objects) ────────────────────────


def build_department_data(
    rng: random.Random, fake: Faker, name: str, color: str, parent_pk: str | None
) -> dict[str, Any]:
    return {
        "name": name,
        "slug": slugify(name),
        "description": fake.sentence(nb_words=10),
        "budget": Decimal(rng.randint(150, 3000) * 1000),
        "headcount": 0,  # backfilled once real employee counts are known
        "color": color,
        "is_active": True,
        "parent": parent_pk,
    }


def build_employee_data(
    rng: random.Random, fake: Faker, index: int, department_pk: str
) -> tuple[dict[str, Any], Path | None]:
    first, last = fake.first_name(), fake.last_name()
    local_part = re.sub(r"[^a-z0-9]+", ".", f"{first}.{last}".lower()).strip(".")
    employment_type = pick(rng, EMPLOYMENT_TYPES)
    salary_range = {
        "full_time": (55, 230),
        "part_time": (28, 90),
        "contractor": (70, 210),
        "intern": (30, 45),
    }[employment_type]
    salary = None
    if not (employment_type == "contractor" and rng.random() < 0.8):
        salary = Decimal(rng.randint(*salary_range) * 1000)
    skills = rng.sample(SKILLS, k=rng.randint(0, 6))

    hire_date = fake.date_between(start_date="-12y")
    # EmployeeView.validate() rejects a date_of_birth less than 16 years
    # before hire_date. Going through days (rather than replacing the year,
    # which can hit Feb 29) keeps this simple and always well past the cutoff.
    years_before_hire = rng.randint(16, 60)
    date_of_birth = hire_date - timedelta(
        days=round(years_before_hire * 365.25) + rng.randint(0, 364)
    )

    data = {
        "name": f"{first} {last}",
        "email": f"{local_part}.{index}@example.com",
        "phone": fake.phone_number() if rng.random() < 0.85 else None,
        "date_of_birth": date_of_birth,
        "hire_date": hire_date,
        "job_title": fake.job(),
        "employment_type": employment_type,
        "salary": salary,
        "skills": skills,
        "is_active": rng.random() < 0.97,
        "department": department_pk,
    }

    avatar_asset: Path | None = None
    roll = rng.randint(1, 10)
    if roll <= 2:
        avatar_asset = rng.choice(sorted(ASSETS_DIR.glob("avatar0*.png")))
    return data, avatar_asset


def build_project_data(
    rng: random.Random, fake: Faker, index: int, department_pk: str
) -> dict[str, Any]:
    name = fake.catch_phrase().title()
    status = pick(rng, PROJECT_STATUSES)
    start = fake.date_between(start_date="-3y", end_date="+2M")
    budget = rng.randint(20, 500) * 1000
    estimated = rng.randint(100, 2000)
    progress = {
        "planning": 0.0,
        "active": rng.uniform(0.1, 0.9),
        "on_hold": rng.uniform(0.1, 0.7),
        "completed": rng.uniform(0.9, 1.2),
        "cancelled": rng.uniform(0.0, 0.6),
    }[status]
    end_date: date | None = None
    if status in ("completed", "cancelled"):
        end_date = start + timedelta(days=rng.randint(30, 540))
    return {
        "name": name,
        "slug": f"{slugify(name)}-{index}",
        "description": fake.paragraph(nb_sentences=2),
        "status": status,
        "priority": pick(rng, PRIORITIES),
        "department": department_pk,
        "budget": Decimal(budget),
        "spent": Decimal(f"{budget * progress:.2f}"),
        "estimated_hours": Decimal(f"{estimated}.0"),
        "actual_hours": Decimal(f"{estimated * progress:.1f}"),
        "start_date": start,
        "end_date": end_date,
        "plan": {"milestones": [fake.bs() for _ in range(rng.randint(2, 4))]}
        if rng.random() < 0.3
        else None,
    }


def build_task_data(
    rng: random.Random,
    fake: Faker,
    project_pk: str,
    employee_pks: list[str],
) -> dict[str, Any]:
    status = pick(rng, TASK_STATUSES)
    data: dict[str, Any] = {
        "title": fake.sentence(nb_words=6).rstrip("."),
        "project": project_pk,
        "status": status,
        "priority": pick(rng, PRIORITIES),
        "estimated_hours": Decimal(f"{rng.randint(2, 80) / 2:.1f}"),
        "actual_hours": Decimal("0.0"),
        "sort": rng.randint(0, 50),
        "assignee": rng.choice(employee_pks) if rng.random() < 0.85 else None,
        "description": fake.paragraph(nb_sentences=2) if rng.random() < 0.5 else None,
        "due_date": fake.date_between(start_date="-3M", end_date="+3M")
        if rng.random() < 0.7
        else None,
        "labels": rng.sample(TASK_LABELS, k=rng.randint(1, 3))
        if rng.random() < 0.4
        else None,
    }
    if status == "completed":
        data["completed_at"] = fake.date_time_between(start_date="-6M", end_date="now")
        data["actual_hours"] = Decimal(f"{rng.randint(2, 90) / 2:.1f}")
    return data


def build_timesheet_data(
    rng: random.Random,
    fake: Faker,
    employee_pks: list[str],
    project_pks: list[str],
    task_refs: list[tuple[str, str]],  # (task_pk, project_pk)
) -> dict[str, Any]:
    if task_refs and rng.random() < 0.6:
        task_pk, project_pk = rng.choice(task_refs)
    else:
        task_pk, project_pk = None, rng.choice(project_pks)
    hours = (Decimal(rng.randint(1, 18)) / 2).quantize(Decimal("0.1"))
    rate = Decimal(rng.choice([0, 0, 60, 75, 90, 110, 140]))
    return {
        "employee": rng.choice(employee_pks),
        "project": project_pk,
        "task": task_pk,
        "date": fake.date_between(start_date="-1y"),
        "hours": hours,
        "minutes": rng.choice([0, 0, 15, 30, 45]),
        "is_billable": rng.random() < 0.8,
        "hourly_rate": rate,
        "total_cost": (hours * rate).quantize(Decimal("0.01")),
        "description": fake.sentence(nb_words=8) if rng.random() < 0.5 else None,
    }


def build_leave_request_data(
    rng: random.Random, fake: Faker, employee_pks: list[str]
) -> dict[str, Any]:
    status = pick(rng, LEAVE_STATUSES)
    start = fake.date_between(start_date="-6M", end_date="+6M")
    days = rng.randint(1, 10)
    data: dict[str, Any] = {
        "employee": rng.choice(employee_pks),
        "type": pick(rng, LEAVE_TYPES),
        "status": status,
        "start_date": start,
        "end_date": start + timedelta(days=days - 1),
        "days_requested": Decimal(days),
        "reason": fake.sentence(nb_words=8),
    }
    if status in ("approved", "rejected", "taken"):
        data["approver"] = rng.choice(employee_pks)
        reviewed = datetime.combine(
            start - timedelta(days=rng.randint(1, 30)), datetime.min.time()
        ) + timedelta(hours=rng.randint(8, 18))
        data["reviewed_at"] = reviewed
        if rng.random() < 0.4:
            data["reviewer_notes"] = fake.sentence(nb_words=6)
    return data


def build_expense_data(
    rng: random.Random,
    fake: Faker,
    index: int,
    employee_pks: list[str],
    project_pks: list[str],
) -> dict[str, Any]:
    # Lines are only reachable as an inline of the create/edit form (there is
    # no standalone `/expense-line/create`), so this leaves them out and lets
    # `ExpenseView.after_create_committed` recompute `total_amount` as 0 --
    # a documented simplification versus seed.py, which writes lines directly.
    status = pick(rng, EXPENSE_STATUSES)
    data: dict[str, Any] = {
        "employee": rng.choice(employee_pks),
        "project": rng.choice(project_pks) if rng.random() < 0.7 else None,
        "expense_number": f"EXP-{2000 + index}",
        "status": status,
        "category": pick(rng, EXPENSE_CATEGORIES),
        "description": fake.sentence(nb_words=8),
        "notes": fake.sentence(nb_words=6) if rng.random() < 0.3 else None,
    }
    if status != "draft":
        submitted = fake.date_time_between(start_date="-1y", end_date="now")
        data["submitted_at"] = submitted
        if status in ("approved", "reimbursed"):
            data["approved_at"] = submitted + timedelta(days=rng.randint(1, 14))
            data["approved_by"] = rng.choice(employee_pks)
    return data


# ── Main ─────────────────────────────────────────────────────────────────────


def _progress(label: str, i: int, total: int) -> None:
    if (i + 1) % 50 == 0 or i + 1 == total:
        print(f"\r  {label}: {i + 1}/{total}", end="", flush=True)
    if i + 1 == total:
        print()


def seed_via_api(client: AdminApiClient, config: SeedConfig) -> None:
    rng = random.Random(config.seed)
    Faker.seed(config.seed)
    fake = Faker()
    counts = scaled_counts(config)
    started = time.perf_counter()

    if config.reset:
        print(
            "Resetting schema directly through SQLAlchemy (no admin endpoint for this)..."
        )
        Base.metadata.drop_all(app_engine)
        for stale in (avatars_storage.base_dir / AVATAR_UPLOAD_FOLDER).glob("*"):
            stale.unlink()
    Base.metadata.create_all(app_engine)

    # Departments: sequential, parent before child, same constraint as
    # seed.py -- a child's `parent=` needs the parent's pk, which only
    # exists once that parent's create request has already come back.
    children_of: dict[str | None, list[str]] = defaultdict(list)
    for name, parent_name, _color in ORG_CHART:
        children_of[parent_name].append(name)

    department_pks: dict[str, str] = {}
    department_payloads: dict[str, dict[str, Any]] = {}
    for name, parent_name, color in ORG_CHART:
        data = build_department_data(
            rng, fake, name, color, department_pks.get(parent_name)
        )
        department_pks[name] = client.create("department", clean(data))
        department_payloads[name] = data
    print(f"  departments: {len(ORG_CHART)}/{len(ORG_CHART)}")

    leaf_names = [n for n in department_pks if not children_of[n]]
    parent_names = [n for n in department_pks if children_of[n]]

    # Employees
    employee_pks: list[str] = []
    dept_headcount: Counter[str] = Counter()
    total_employees = counts["employees"]
    for i in range(total_employees):
        department_name = pick_department(rng, leaf_names, parent_names)
        data, avatar_asset = build_employee_data(
            rng, fake, i, department_pks[department_name]
        )
        files = None
        if avatar_asset is not None:
            files = {
                "avatar": (avatar_asset.name, avatar_asset.read_bytes(), "image/png")
            }
        employee_pks.append(client.create("employee", clean(data), files=files))
        dept_headcount[department_name] += 1
        _progress("employees", i, total_employees)

    # Real headcount, now that every employee has a department. Full-form
    # edit, since `/{key}/edit` replaces every field the view exposes.
    for name, payload in department_payloads.items():
        payload["headcount"] = dept_headcount.get(name, 0)
        client.edit("department", department_pks[name], clean(payload))

    # Projects
    project_pks: list[str] = []
    all_department_pks = list(department_pks.values())
    total_projects = counts["projects"]
    for i in range(total_projects):
        data = build_project_data(rng, fake, i, rng.choice(all_department_pks))
        project_pks.append(client.create("project", clean(data)))
        _progress("projects", i, total_projects)

    # Tasks
    task_refs: list[tuple[str, str]] = []  # (task_pk, project_pk)
    total_tasks = counts["tasks"]
    for i in range(total_tasks):
        project_pk = rng.choice(project_pks)
        data = build_task_data(rng, fake, project_pk, employee_pks)
        task_pk = client.create("task", clean(data))
        task_refs.append((task_pk, project_pk))
        _progress("tasks", i, total_tasks)

    # Timesheets
    total_timesheets = counts["timesheets"]
    for i in range(total_timesheets):
        data = build_timesheet_data(rng, fake, employee_pks, project_pks, task_refs)
        client.create("timesheet", clean(data))
        _progress("timesheets", i, total_timesheets)

    # Leave requests
    total_leave = counts["leave_requests"]
    for i in range(total_leave):
        data = build_leave_request_data(rng, fake, employee_pks)
        client.create("leave-request", clean(data))
        _progress("leave requests", i, total_leave)

    # Expenses
    total_expenses = counts["expenses"]
    for i in range(total_expenses):
        data = build_expense_data(rng, fake, i, employee_pks, project_pks)
        client.create("expense", clean(data))
        _progress("expenses", i, total_expenses)

    # Soft-delete a small slice last: SoftDeleteModelView.get_detail_query
    # hides a deleted row, and every relation resolves through the target
    # view's find_by_pk, so deleting any earlier would break creates that
    # still needed to reference these employees/projects.
    deleted_employees = rng.sample(employee_pks, k=max(1, len(employee_pks) // 50))
    client.bulk_action("employee", "delete", deleted_employees)
    deleted_projects = rng.sample(project_pks, k=max(1, len(project_pks) // 25))
    client.bulk_action("project", "delete", deleted_projects)

    elapsed = time.perf_counter() - started
    total = len(ORG_CHART) + sum(counts.values())
    print(f"Done: {total} records created in {elapsed:.1f}s -> {client.http.base_url}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the 07-hr example through the running admin's HTTP "
        "endpoints (login + CSRF included), instead of writing to the "
        "database directly like seed.py does."
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the running app (default: %(default)s).",
    )
    parser.add_argument(
        "--username", default="admin", help="Admin login (default: %(default)s)."
    )
    parser.add_argument(
        "--password", default="password", help="Admin password (default: %(default)s)."
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Global multiplier every entity count scales from proportionally "
        "(default: %(default)s).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible data (default: %(default)s).",
    )
    parser.add_argument(
        "--no-reset",
        dest="reset",
        action="store_false",
        help="Append to the existing database instead of wiping it first "
        "(unique fields like email/slug may then collide across runs).",
    )
    args = parser.parse_args()
    client = AdminApiClient(args.base_url, args.username, args.password)
    seed_via_api(
        client,
        SeedConfig(scale=args.scale, seed=args.seed, reset=args.reset),
    )


if __name__ == "__main__":
    main()
