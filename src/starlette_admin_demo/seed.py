"""Standalone seed script: generates a Faker dataset and writes it straight
to the database through the app's own SQLAlchemy table metadata (no running
app or HTTP round trip needed).

Usage:
    uv run seed                # default volumes
    uv run seed --scale 5      # about five times as much data
    uv run seed --scale 3500   # roughly a million employees

Departments come from a fixed org chart (`ORG_CHART`) and don't scale.
Every other entity's volume is `round(base_count * scale)` (`BASE_COUNTS`,
`scaled_counts()`).

Built to stay fast at millions of rows:

- Rows are plain dicts pushed through Core INSERT executemany in
  `CHUNK_SIZE` batches (`insert_chunked`) - no ORM instances, identity map,
  or per-row flush, and memory stays flat regardless of `--scale`.
- Primary keys are assigned up front (`next_id`), so foreign keys are plain
  integer draws from a `range` and no RETURNING round trip is needed.
- Faker only runs while filling `TextPools`; the actual rows sample those
  pools with `random`, which is orders of magnitude cheaper per row.
- The ~20% of employees with an avatar share seven files copied once from
  `assets/avatar01-07.png` instead of getting one copy each.
- On SQLite, journalling/fsync are relaxed for the seeding connection; the
  dataset is disposable and rebuilt from scratch on any failure.
"""

import argparse
import random
import re
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Sequence

from faker import Faker
from PIL import Image
from sqlalchemy import Connection, Table, bindparam, func, select
from starlette_admin.storage import FileInfo, secure_filename

from .config import avatars_storage
from .config import engine as app_engine
from .models import (
    Base,
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
    Timesheet,
)

ASSETS_DIR = Path(__file__).parent / "assets"
AVATAR_UPLOAD_FOLDER = "avatars"

# Rows per executemany batch; also how often progress prints and commits run.
CHUNK_SIZE = 10_000

# Fixed org chart: (name, parent name, color); parents listed before children
# so each parent's id exists when its child row is built. Executive plus the
# seven division heads are umbrella nodes; the rest are leaf teams most
# employees actually belong to (see `pick_department`).
ORG_CHART: list[tuple[str, str | None, str]] = [
    ("Executive", None, "#6b7280"),
    ("Engineering", "Executive", "#3b82f6"),
    ("Platform", "Engineering", "#0ea5e9"),
    ("Backend", "Engineering", "#2563eb"),
    ("Frontend", "Engineering", "#8b5cf6"),
    ("Mobile", "Engineering", "#6366f1"),
    ("QA & Release", "Engineering", "#14b8a6"),
    ("Data & Analytics", "Engineering", "#0891b2"),
    ("Security", "Engineering", "#ef4444"),
    ("Sales", "Executive", "#22c55e"),
    ("Enterprise Sales", "Sales", "#16a34a"),
    ("SMB Sales", "Sales", "#4ade80"),
    ("Sales Operations", "Sales", "#84cc16"),
    ("Marketing", "Executive", "#f59e0b"),
    ("Growth", "Marketing", "#fbbf24"),
    ("Brand & Content", "Marketing", "#f97316"),
    ("Customer Success", "Executive", "#06b6d4"),
    ("Support", "Customer Success", "#67e8f9"),
    ("Onboarding", "Customer Success", "#22d3ee"),
    ("Finance", "Executive", "#a855f7"),
    ("Accounting", "Finance", "#c084fc"),
    ("Procurement", "Finance", "#9333ea"),
    ("People Ops", "Executive", "#ec4899"),
    ("Recruiting", "People Ops", "#f472b6"),
    ("Operations", "Executive", "#eab308"),
    ("IT & Workplace", "Operations", "#facc15"),
]

SKILLS = [
    "python", "typescript", "rust", "go", "sql", "postgres", "sqlalchemy",
    "react", "kubernetes", "terraform", "aws", "gcp", "ci-cd", "grafana",
    "leadership", "mentoring", "negotiation", "crm", "seo", "copywriting",
    "figma", "accounting", "recruiting", "public-speaking",
]  # fmt: skip

TASK_LABELS = [
    "backend", "frontend", "infra", "design", "bug", "research",
    "customer", "urgent", "tech-debt", "docs",
]  # fmt: skip

EMPLOYMENT_TYPES = [
    ("full_time", 72), ("part_time", 10), ("contractor", 12), ("intern", 6),
]  # fmt: skip

SALARY_RANGES = {
    "full_time": (55, 230),
    "part_time": (28, 90),
    "contractor": (70, 210),
    "intern": (30, 45),
}

PROJECT_STATUSES = [
    ("planning", 20), ("active", 40), ("on_hold", 10),
    ("completed", 25), ("cancelled", 5),
]  # fmt: skip

# How far along a project is for a given status, as a uniform range.
PROGRESS_RANGES = {
    "planning": (0.0, 0.0),
    "active": (0.1, 0.9),
    "on_hold": (0.1, 0.7),
    "completed": (0.9, 1.2),
    "cancelled": (0.0, 0.6),
}

TASK_STATUSES = [
    ("backlog", 20), ("todo", 20), ("in_progress", 20),
    ("in_review", 10), ("completed", 25), ("cancelled", 5),
]  # fmt: skip

PRIORITIES = [("low", 25), ("medium", 45), ("high", 22), ("critical", 8)]

LEAVE_TYPES = [
    ("annual", 45), ("sick", 25), ("personal", 15),
    ("unpaid", 5), ("parental", 10),
]  # fmt: skip

LEAVE_STATUSES = [
    ("pending", 25), ("approved", 40), ("rejected", 10),
    ("taken", 20), ("cancelled", 5),
]  # fmt: skip

EXPENSE_CATEGORIES = [
    ("travel", 25), ("meals", 20), ("supplies", 15),
    ("equipment", 15), ("software", 20), ("other", 5),
]  # fmt: skip

EXPENSE_STATUSES = [
    ("draft", 15), ("submitted", 30), ("approved", 25),
    ("rejected", 10), ("reimbursed", 20),
]  # fmt: skip

HOURLY_RATES = tuple(Decimal(r) for r in (0, 0, 60, 75, 90, 110, 140))
HALF_HOURS = tuple((Decimal(n) / 2).quantize(Decimal("0.1")) for n in range(1, 19))

TODAY_ORDINAL = date.today().toordinal()


# ── Global scale config ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class SeedConfig:
    """The one knob every entity count scales from: each count is
    `round(base_count * scale)` against `BASE_COUNTS`."""

    scale: float = 1.0
    seed: int = 42
    reset: bool = True


# Volumes at scale=1.0. `Department` isn't listed: the org chart is fixed.
BASE_COUNTS: dict[str, int] = {
    "employees": 300,
    "projects": 30,
    "tasks": 150,
    "timesheets": 500,
    "leave_requests": 80,
    "expenses": 100,
}

MIN_COUNTS: dict[str, int] = {
    "employees": 5,
    "projects": 2,
    "tasks": 5,
    "timesheets": 5,
    "leave_requests": 3,
    "expenses": 2,
}


def scaled_counts(config: SeedConfig) -> dict[str, int]:
    """Every entity's volume, proportional to `config.scale`."""
    return {
        key: max(MIN_COUNTS[key], round(base * config.scale))
        for key, base in BASE_COUNTS.items()
    }


# ── Small helpers ────────────────────────────────────────────────────────────


def pick(rng: random.Random, table: list[tuple[str, int]]) -> str:
    values, weights = zip(*table)
    return rng.choices(values, weights=weights, k=1)[0]


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def rand_date(rng: random.Random, days_back: int, days_forward: int = 0) -> date:
    return date.fromordinal(TODAY_ORDINAL + rng.randint(-days_back, days_forward))


def rand_datetime(rng: random.Random, days_back: int) -> datetime:
    return datetime.combine(
        rand_date(rng, days_back), datetime.min.time()
    ) + timedelta(minutes=rng.randint(0, 1439))


def attach_avatar(asset: Path, dims: tuple[int, int]) -> dict[str, Any]:
    """Copy `asset` into `avatars_storage` and return the same `FileInfo`
    dict shape an `ImageField` upload would store on `Employee.avatar`."""
    filename = secure_filename(asset.name)
    path = avatars_storage.base_dir / AVATAR_UPLOAD_FOLDER / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    while path.exists():
        path = path.with_name(f"{uuid.uuid4().hex[:8]}_{path.name}")
    path.write_bytes(asset.read_bytes())
    width, height = dims
    return FileInfo(
        filename=path.name,
        content_type="image/png",
        size=path.stat().st_size,
        storage=avatars_storage.name,
        key=path.relative_to(avatars_storage.base_dir).as_posix(),
        uploaded_at=datetime.now(timezone.utc),
        width=width,
        height=height,
    ).to_dict()


def next_id(conn: Connection, column: Any) -> int:
    """Bulk executemany can't hand back autoincrement ids, so every row's pk
    is assigned up front; starting past MAX(id) keeps `--no-reset` runs from
    colliding with existing rows."""
    return (conn.execute(select(func.max(column))).scalar() or 0) + 1


def insert_rows(conn: Connection, table: Table, rows: list[dict[str, Any]]) -> None:
    """executemany requires every dict in a batch to share one key set, so
    group by key set first. Builders rely on this to omit a column entirely
    (e.g. `avatar`) when it should stay SQL NULL - passing None to a JSON
    column would store the JSON literal 'null' instead."""
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row)].append(row)
    for group in groups.values():
        conn.execute(table.insert(), group)


def insert_chunked(
    conn: Connection,
    table: Table,
    label: str,
    total: int,
    build_row: Callable[[int], dict[str, Any]],
) -> None:
    """Call `build_row(index)` `total` times, inserting and committing every
    `CHUNK_SIZE` rows so memory use stays flat at any `--scale`."""
    done = 0
    while done < total:
        batch = [build_row(i) for i in range(done, min(done + CHUNK_SIZE, total))]
        insert_rows(conn, table, batch)
        conn.commit()
        done += len(batch)
        print(f"\r  {label}: {done}/{total}", end="", flush=True)
    print()


# ── Text pools ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TextPools:
    """Faker output generated once up front and sampled per row. Faker calls
    dominate build time at large scales; a few thousand calls here replace
    millions during row building. Name pools carry a pre-cleaned email token
    so building an address needs no regex per employee."""

    first_names: list[tuple[str, str]]  # (display, email-safe token)
    last_names: list[tuple[str, str]]
    jobs: list[str]
    phones: list[str]
    titles: list[str]  # 6-word sentences, no trailing period
    line_items: list[str]  # 4-word sentences, no trailing period
    sentences6: list[str]
    sentences8: list[str]
    paragraphs: list[str]
    catch_phrases: list[tuple[str, str]]  # (title-cased name, slug)
    buzz_phrases: list[str]


def _email_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")


def build_text_pools(fake: Faker) -> TextPools:
    return TextPools(
        first_names=[
            (name, _email_token(name))
            for name in (fake.first_name() for _ in range(400))
        ],
        last_names=[
            (name, _email_token(name))
            for name in (fake.last_name() for _ in range(400))
        ],
        jobs=[fake.job() for _ in range(300)],
        phones=[fake.phone_number() for _ in range(400)],
        titles=[fake.sentence(nb_words=6).rstrip(".") for _ in range(500)],
        line_items=[fake.sentence(nb_words=4).rstrip(".") for _ in range(300)],
        sentences6=[fake.sentence(nb_words=6) for _ in range(300)],
        sentences8=[fake.sentence(nb_words=8) for _ in range(500)],
        paragraphs=[fake.paragraph(nb_sentences=2) for _ in range(400)],
        catch_phrases=[
            (name, slugify(name))
            for name in (fake.catch_phrase().title() for _ in range(400))
        ],
        buzz_phrases=[fake.bs() for _ in range(200)],
    )


# ── Row builders ─────────────────────────────────────────────────────────────


def pick_department(
    rng: random.Random,
    leaf_departments: Sequence[Any],
    parent_departments: Sequence[Any],
) -> Any:
    """Most employees belong to a leaf team; a small slice reports directly
    to a division head (an umbrella department with children), the way a
    VP's own direct reports would sit a level above any one team.
    """
    if parent_departments and rng.random() < 0.08:
        return rng.choice(parent_departments)
    return rng.choice(leaf_departments)


def build_employee_row(
    rng: random.Random,
    pools: TextPools,
    employee_id: int,
    department_id: int,
    avatar_infos: list[dict[str, Any]],
    deleted: bool,
) -> dict[str, Any]:
    first, first_local = rng.choice(pools.first_names)
    last, last_local = rng.choice(pools.last_names)
    employment_type = pick(rng, EMPLOYMENT_TYPES)
    # Contractors are usually billed hourly, so most have no annual salary.
    salary = None
    if not (employment_type == "contractor" and rng.random() < 0.8):
        salary = Decimal(rng.randint(*SALARY_RANGES[employment_type]) * 1000)
    skills = rng.sample(SKILLS, k=rng.randint(0, 6))

    row: dict[str, Any] = {
        "id": employee_id,
        "name": f"{first} {last}",
        # The pk suffix keeps emails unique within and across runs.
        "email": f"{first_local}.{last_local}.{employee_id}@example.com",
        "phone": rng.choice(pools.phones) if rng.random() < 0.85 else None,
        "date_of_birth": date.fromordinal(
            TODAY_ORDINAL - rng.randint(20 * 365, 64 * 365)
        ),
        "hire_date": rand_date(rng, 12 * 365),
        "job_title": rng.choice(pools.jobs),
        "employment_type": EmploymentType(employment_type),
        "salary": salary,
        "skills": skills or None,
        "is_active": rng.random() < 0.97,
        "department_id": department_id,
        "deleted_at": rand_datetime(rng, 180) if deleted else None,
    }
    # ~20% chance of an avatar; otherwise the key stays absent so the column
    # is SQL NULL and the UI falls back to initials.
    if rng.randint(1, 10) <= 2:
        row["avatar"] = rng.choice(avatar_infos)
    return row


def build_project_row(
    rng: random.Random,
    pools: TextPools,
    project_id: int,
    department_id: int,
    deleted: bool,
) -> dict[str, Any]:
    name, slug = rng.choice(pools.catch_phrases)
    status = pick(rng, PROJECT_STATUSES)
    start = rand_date(rng, 3 * 365, 60)
    budget = rng.randint(20, 500) * 1000
    estimated = rng.randint(100, 2000)
    progress = rng.uniform(*PROGRESS_RANGES[status])
    end_date: date | None = None
    if status in ("completed", "cancelled"):
        end_date = start + timedelta(days=rng.randint(30, 540))
    return {
        "id": project_id,
        "department_id": department_id,
        "name": name,
        "slug": f"{slug}-{project_id}",
        "description": rng.choice(pools.paragraphs),
        "status": ProjectStatus(status),
        "priority": TaskPriority(pick(rng, PRIORITIES)),
        "budget": Decimal(budget),
        "spent": Decimal(f"{budget * progress:.2f}"),
        "estimated_hours": Decimal(f"{estimated}.0"),
        "actual_hours": Decimal(f"{estimated * progress:.1f}"),
        "start_date": start,
        "end_date": end_date,
        "plan": {"milestones": rng.sample(pools.buzz_phrases, k=rng.randint(2, 4))}
        if rng.random() < 0.3
        else None,
        "deleted_at": rand_datetime(rng, 180) if deleted else None,
    }


def build_task_row(
    rng: random.Random,
    pools: TextPools,
    task_id: int,
    project_id: int,
    employee_ids: range,
) -> dict[str, Any]:
    status = pick(rng, TASK_STATUSES)
    completed = status == "completed"
    return {
        "id": task_id,
        "project_id": project_id,
        "assigned_to": rng.choice(employee_ids) if rng.random() < 0.85 else None,
        "title": rng.choice(pools.titles),
        "description": rng.choice(pools.paragraphs) if rng.random() < 0.5 else None,
        "status": TaskStatus(status),
        "priority": TaskPriority(pick(rng, PRIORITIES)),
        "estimated_hours": Decimal(f"{rng.randint(2, 80) / 2:.1f}"),
        "actual_hours": Decimal(f"{rng.randint(2, 90) / 2:.1f}")
        if completed
        else Decimal("0.0"),
        "due_date": rand_date(rng, 90, 90) if rng.random() < 0.7 else None,
        "completed_at": rand_datetime(rng, 180) if completed else None,
        "labels": rng.sample(TASK_LABELS, k=rng.randint(1, 3))
        if rng.random() < 0.4
        else None,
        "sort": rng.randint(0, 50),
    }


def build_timesheet_row(
    rng: random.Random,
    pools: TextPools,
    employee_ids: range,
    project_ids: range,
    task_ids: range,
    task_project_ids: list[int],
) -> dict[str, Any]:
    # Most entries are logged against a task; the rest go to a project only.
    # Reusing the task's own project keeps the two foreign keys coherent.
    if task_project_ids and rng.random() < 0.6:
        offset = rng.randrange(len(task_project_ids))
        task_id, project_id = task_ids[offset], task_project_ids[offset]
    else:
        task_id, project_id = None, rng.choice(project_ids)
    hours = rng.choice(HALF_HOURS)
    rate = rng.choice(HOURLY_RATES)
    return {
        "employee_id": rng.choice(employee_ids),
        "project_id": project_id,
        "task_id": task_id,
        "date": rand_date(rng, 365),
        "hours": hours,
        "minutes": rng.choice((0, 0, 15, 30, 45)),
        "is_billable": rng.random() < 0.8,
        "hourly_rate": rate,
        "total_cost": (hours * rate).quantize(Decimal("0.01")),
        "description": rng.choice(pools.sentences8) if rng.random() < 0.5 else None,
    }


def build_leave_request_row(
    rng: random.Random, pools: TextPools, employee_ids: range
) -> dict[str, Any]:
    status = pick(rng, LEAVE_STATUSES)
    start = rand_date(rng, 180, 180)
    days = rng.randint(1, 10)
    row: dict[str, Any] = {
        "employee_id": rng.choice(employee_ids),
        "approver_id": None,
        "type": LeaveType(pick(rng, LEAVE_TYPES)),
        "status": LeaveStatus(status),
        "start_date": start,
        "end_date": start + timedelta(days=days - 1),
        "days_requested": Decimal(days),
        "reason": rng.choice(pools.sentences8),
        "reviewer_notes": None,
        "reviewed_at": None,
    }
    if status in ("approved", "rejected", "taken"):
        row["approver_id"] = rng.choice(employee_ids)
        row["reviewed_at"] = datetime.combine(
            start - timedelta(days=rng.randint(1, 30)), datetime.min.time()
        ) + timedelta(hours=rng.randint(8, 18))
        if rng.random() < 0.4:
            row["reviewer_notes"] = rng.choice(pools.sentences6)
    return row


def build_expense_row(
    rng: random.Random,
    pools: TextPools,
    expense_id: int,
    employee_ids: range,
    project_ids: range,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    status = pick(rng, EXPENSE_STATUSES)
    lines: list[dict[str, Any]] = []
    total = Decimal("0")
    for _ in range(rng.randint(1, 3)):
        quantity = rng.randint(1, 5)
        unit_price = (Decimal(rng.randint(500, 40000)) / 100).quantize(Decimal("0.01"))
        amount = (unit_price * quantity).quantize(Decimal("0.01"))
        total += amount
        lines.append(
            {
                "expense_id": expense_id,
                "description": rng.choice(pools.line_items),
                "quantity": quantity,
                "unit_price": unit_price,
                "amount": amount,
                "date": rand_date(rng, 365),
            }
        )
    # `total_amount` is normally recomputed by
    # ExpenseView._recompute_total_amount; done directly here since this
    # script bypasses that hook.
    row: dict[str, Any] = {
        "id": expense_id,
        "employee_id": rng.choice(employee_ids),
        "project_id": rng.choice(project_ids) if rng.random() < 0.7 else None,
        "expense_number": f"EXP-{2000 + expense_id}",
        "status": ExpenseStatus(status),
        "category": ExpenseCategory(pick(rng, EXPENSE_CATEGORIES)),
        "description": rng.choice(pools.sentences8),
        "total_amount": total,
        "submitted_at": None,
        "approved_at": None,
        "approved_by": None,
        "notes": rng.choice(pools.sentences6) if rng.random() < 0.3 else None,
    }
    if status != "draft":
        submitted = rand_datetime(rng, 365)
        row["submitted_at"] = submitted
        if status in ("approved", "reimbursed"):
            row["approved_at"] = submitted + timedelta(days=rng.randint(1, 14))
            row["approved_by"] = rng.choice(employee_ids)
    return row, lines


# ── Main ─────────────────────────────────────────────────────────────────────


def seed(config: SeedConfig) -> None:
    rng = random.Random(config.seed)
    Faker.seed(config.seed)
    fake = Faker()
    counts = scaled_counts(config)
    started = time.perf_counter()

    engine = app_engine
    # The app engine echoes SQL outside PROD; that would print every INSERT
    # statement, which is unusable at million-row volume.
    engine.echo = False

    if config.reset:
        Base.metadata.drop_all(engine)
        for stale in (avatars_storage.base_dir / AVATAR_UPLOAD_FOLDER).glob("*"):
            stale.unlink()

    Base.metadata.create_all(engine)

    pools = build_text_pools(fake)
    # Each asset is copied into storage once; every seeded avatar then reuses
    # one of these FileInfo dicts instead of writing a file per employee.
    avatar_infos = [
        attach_avatar(path, image_size(path))
        for path in sorted(ASSETS_DIR.glob("avatar0*.png"))
    ]

    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            # Seed data is disposable and rebuilt from scratch on failure,
            # so trade crash-durability for insert speed on this connection.
            conn.exec_driver_sql("PRAGMA journal_mode = MEMORY")
            conn.exec_driver_sql("PRAGMA synchronous = OFF")

        # Departments: ids follow ORG_CHART order (parents first), so each
        # child can reference its parent's id before anything is inserted.
        department_id_start = next_id(conn, Department.id)
        department_ids: dict[str, int] = {}
        department_rows: list[dict[str, Any]] = []
        for offset, (name, parent_name, color) in enumerate(ORG_CHART):
            department_ids[name] = department_id_start + offset
            department_rows.append(
                {
                    "id": department_ids[name],
                    "parent_id": department_ids.get(parent_name),
                    "name": name,
                    "slug": slugify(name),
                    "description": fake.sentence(nb_words=10),
                    "budget": Decimal(rng.randint(150, 3000) * 1000),
                    "headcount": 0,  # recomputed once employees exist
                    "color": color,
                    "is_active": True,
                }
            )
        insert_rows(conn, Department.__table__, department_rows)
        conn.commit()
        print(f"  departments: {len(ORG_CHART)}/{len(ORG_CHART)}")

        parent_names = {parent for _, parent, _ in ORG_CHART if parent}
        leaf_ids = [i for n, i in department_ids.items() if n not in parent_names]
        umbrella_ids = [i for n, i in department_ids.items() if n in parent_names]
        all_department_ids = list(department_ids.values())

        employee_id_start = next_id(conn, Employee.id)
        employee_ids = range(employee_id_start, employee_id_start + counts["employees"])
        # Soft-delete a small slice, so SoftDeleteModelView's "hidden on
        # delete" behavior is observable on a fresh dataset. Chosen up front
        # so the stamp happens at build time instead of a second UPDATE pass.
        deleted_employees = set(
            rng.sample(employee_ids, k=max(1, len(employee_ids) // 50))
        )
        headcounts: Counter[int] = Counter()

        def employee_row(i: int) -> dict[str, Any]:
            department_id = pick_department(rng, leaf_ids, umbrella_ids)
            headcounts[department_id] += 1
            return build_employee_row(
                rng,
                pools,
                employee_ids[i],
                department_id,
                avatar_infos,
                employee_ids[i] in deleted_employees,
            )

        insert_chunked(
            conn, Employee.__table__, "employees", len(employee_ids), employee_row
        )

        # Real headcount, now that every employee has a department.
        conn.execute(
            Department.__table__.update()
            .where(Department.__table__.c.id == bindparam("b_id"))
            .values(headcount=bindparam("b_headcount")),
            [
                {"b_id": dept_id, "b_headcount": headcounts.get(dept_id, 0)}
                for dept_id in all_department_ids
            ],
        )
        conn.commit()

        project_id_start = next_id(conn, Project.id)
        project_ids = range(project_id_start, project_id_start + counts["projects"])
        deleted_projects = set(
            rng.sample(project_ids, k=max(1, len(project_ids) // 25))
        )
        insert_chunked(
            conn,
            Project.__table__,
            "projects",
            len(project_ids),
            lambda i: build_project_row(
                rng,
                pools,
                project_ids[i],
                rng.choice(all_department_ids),
                project_ids[i] in deleted_projects,
            ),
        )

        task_id_start = next_id(conn, Task.id)
        task_ids = range(task_id_start, task_id_start + counts["tasks"])
        # Remembered per task so timesheets can keep task/project coherent.
        task_project_ids: list[int] = []

        def task_row(i: int) -> dict[str, Any]:
            project_id = rng.choice(project_ids)
            task_project_ids.append(project_id)
            return build_task_row(rng, pools, task_ids[i], project_id, employee_ids)

        insert_chunked(conn, Task.__table__, "tasks", len(task_ids), task_row)

        insert_chunked(
            conn,
            Timesheet.__table__,
            "timesheets",
            counts["timesheets"],
            lambda _: build_timesheet_row(
                rng, pools, employee_ids, project_ids, task_ids, task_project_ids
            ),
        )

        insert_chunked(
            conn,
            LeaveRequest.__table__,
            "leave requests",
            counts["leave_requests"],
            lambda _: build_leave_request_row(rng, pools, employee_ids),
        )

        # Expenses and their lines are built together (the lines' sum is the
        # expense's total_amount), so this one interleaves two inserts per
        # chunk instead of going through insert_chunked.
        expense_id_start = next_id(conn, Expense.id)
        total_expenses = counts["expenses"]
        done = 0
        while done < total_expenses:
            expense_batch: list[dict[str, Any]] = []
            line_batch: list[dict[str, Any]] = []
            for i in range(done, min(done + CHUNK_SIZE, total_expenses)):
                row, lines = build_expense_row(
                    rng, pools, expense_id_start + i, employee_ids, project_ids
                )
                expense_batch.append(row)
                line_batch.extend(lines)
            insert_rows(conn, Expense.__table__, expense_batch)
            insert_rows(conn, ExpenseLine.__table__, line_batch)
            conn.commit()
            done += len(expense_batch)
            print(f"\r  expenses: {done}/{total_expenses}", end="", flush=True)
        print()

    elapsed = time.perf_counter() - started
    total = len(ORG_CHART) + sum(counts.values())
    print(f"Done: {total} records created in {elapsed:.1f}s -> {engine.url}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the 07-hr example database directly through SQLAlchemy."
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Global multiplier every entity count scales from proportionally "
        "(the department org chart is fixed and does not scale); "
        "higher means more records (default: %(default)s).",
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
        "(unique fields like slug may then collide across runs).",
    )
    args = parser.parse_args()
    seed(
        SeedConfig(
            scale=args.scale,
            seed=args.seed,
            reset=args.reset,
        )
    )


if __name__ == "__main__":
    main()
