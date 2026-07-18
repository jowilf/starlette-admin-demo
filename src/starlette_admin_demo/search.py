"""Everything behind the admin's search bars: Postgres full-text search.

Every model in models.py carries a trigger-maintained `search_vector` tsvector with a
GIN index, which a view's search bar matches via a prefix tsquery (`build_tsquery`/
`fts_match`, see `ModelView.get_search_query` in views.py). Vectors are maintained by
triggers rather than generated columns because each row's vector also folds in the
*names* of related rows it points at (e.g. an Employee's department), which a
generated column can't reference; renaming a referenced row re-stamps its dependants'
vectors asynchronously via the `SearchRestampJob` outbox rather than inside the
renaming transaction, to avoid rewriting e.g. 100k Employee rows synchronously.
"""

import os
import re
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DDL,
    DateTime,
    Index,
    Integer,
    String,
    event,
    false,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, Session, mapped_column
from starlette_admin.events import (
    AdminEvent,
    AdminEventSubscriber,
    AfterEditContext,
    AfterImportContext,
    on,
)

from .config import engine

# Runs of unicode alphanumerics: strips tsquery operators/punctuation so arbitrary
# input can never produce a tsquery syntax error. Splitting on '_' too costs
# phrase-matching of snake_case terms, but guarantees no token normalizes to zero lexemes.
_TOKENS = re.compile(r"[^\W_]+", re.UNICODE)


def build_tsquery(term: str) -> Any | None:
    """Prefix tsquery for `term`, or None when no searchable token remains."""
    tokens = _TOKENS.findall(term)
    if not tokens:
        return None
    return func.to_tsquery("simple", " & ".join(f"{token}:*" for token in tokens))


def fts_match(model: Any, term: str) -> Any:
    """WHERE clause matching `term` against `model.search_vector`."""
    tsquery = build_tsquery(term)
    if tsquery is None:
        return false()
    return model.search_vector.bool_op("@@")(tsquery)


def search_vector_column() -> Mapped[str | None]:
    """A trigger-maintained `search_vector` column; the trigger populating it
    is registered with `_search_trigger` below."""
    return mapped_column(TSVECTOR, nullable=True)


def search_vector_index(table: str) -> Index:
    return Index(f"ix_{table}_search_vector", "search_vector", postgresql_using="gin")


# Deferred so this module can be imported before *or* after models.py; only
# `_ddl` onward actually needs `Base`.
from .models import Base  # noqa: E402


def _ddl(statement: str) -> None:
    event.listen(Base.metadata, "after_create", DDL(statement))


def _related_name(table: str, fk: str, column: str = "name") -> str:
    """Trigger-expression SQL: `column` of the row `new.{fk}` points at."""
    return f"coalesce((select r.{column} from {table} r where r.id = new.{fk}), '')"


def _search_trigger(table: str, *weighted: tuple[str, str]) -> None:
    """BEFORE INSERT OR UPDATE trigger recomputing `table`'s `search_vector` from
    `(sql_expression, weight)` pairs; expressions read `new.*` and may subselect
    related rows (`_related_name`). Weights (A > B > C > D) keep `ts_rank` ordering
    possible later without a schema change."""
    vector = " || ".join(
        f"setweight(to_tsvector('simple', {sql}), '{weight}')"
        for sql, weight in weighted
    )
    _ddl(
        f"CREATE OR REPLACE FUNCTION {table}_search_vector_refresh() "
        f"RETURNS trigger LANGUAGE plpgsql AS $$ "
        f"BEGIN new.search_vector := {vector}; RETURN new; END $$"
    )
    _ddl(
        f"CREATE OR REPLACE TRIGGER {table}_search_vector_refresh "
        f"BEFORE INSERT OR UPDATE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {table}_search_vector_refresh()"
    )


# Consulted by `process_restamp_jobs` below to walk each `(dep_table, fk)` pair,
# keyed by `f"{table}_{column}"` matching `SearchRestampJob.kind`.
RESTAMP_DEPENDENTS: dict[str, list[tuple[str, str]]] = {}


class SearchRestampJob(Base):
    """Outbox row written by a `_restamp_dependents_on_rename` trigger when the row it
    watches is renamed; `kind` keys into `RESTAMP_DEPENDENTS`, `source_id` is the
    renamed row's id. Drained and deleted by `process_restamp_jobs`, so this table
    should normally sit empty."""

    __tablename__ = "search_restamp_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def _restamp_dependents_on_rename(
    table: str, column: str, dependents: list[tuple[str, str]]
) -> None:
    """AFTER UPDATE trigger: when `table`.`column` changes, enqueue a single
    `SearchRestampJob` outbox row instead of touching every dependent row
    synchronously. `process_restamp_jobs` below drains the outbox and fires each
    dependant's refresh trigger in chunks."""
    kind = f"{table}_{column}"
    RESTAMP_DEPENDENTS[kind] = dependents
    fn = f"{table}_{column}_restamp"
    _ddl(
        f"CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger "
        f"LANGUAGE plpgsql AS $$ BEGIN "
        f"INSERT INTO search_restamp_jobs (kind, source_id, created_at) "
        f"VALUES ('{kind}', new.id, now()); "
        f"RETURN null; END $$"
    )
    _ddl(
        f"CREATE OR REPLACE TRIGGER {fn} "
        f"AFTER UPDATE OF {column} ON {table} FOR EACH ROW "
        f"WHEN (old.{column} IS DISTINCT FROM new.{column}) "
        f"EXECUTE FUNCTION {fn}()"
    )


# One refresh trigger per table: local columns at weights A-C, related rows'
# names at D. Enum casts (`::text`) are fine here - the IMMUTABLE requirement
# that generated columns impose doesn't apply inside a trigger.

_search_trigger(
    "departments",
    ("coalesce(new.name, '') || ' ' || coalesce(new.slug, '')", "A"),
    ("coalesce(new.description, '')", "B"),
    (_related_name("departments", "parent_id"), "D"),
)
_search_trigger(
    "employees",
    ("coalesce(new.name, '')", "A"),
    # `translate` splits emails on '@'/'.' so "doe" matches john.doe@acme.com.
    (
        "translate(coalesce(new.email, ''), '@.', '  ') "
        "|| ' ' || coalesce(new.job_title, '')",
        "B",
    ),
    ("coalesce(new.phone, '')", "C"),
    (_related_name("departments", "department_id"), "D"),
)
_search_trigger(
    "leave_requests",
    ("coalesce(new.reason, '')", "A"),
    ("new.type::text || ' ' || new.status::text", "B"),
    ("coalesce(new.reviewer_notes, '')", "C"),
    (
        _related_name("employees", "employee_id")
        + " || ' ' || "
        + _related_name("employees", "approver_id"),
        "D",
    ),
)
_search_trigger(
    "projects",
    ("coalesce(new.name, '') || ' ' || coalesce(new.slug, '')", "A"),
    ("new.status::text || ' ' || new.priority::text", "B"),
    ("coalesce(new.description, '')", "C"),
    (_related_name("departments", "department_id"), "D"),
)
_search_trigger(
    "tasks",
    ("coalesce(new.title, '')", "A"),
    ("new.status::text || ' ' || new.priority::text", "B"),
    ("coalesce(new.description, '')", "C"),
    (
        _related_name("projects", "project_id")
        + " || ' ' || "
        + _related_name("employees", "assigned_to"),
        "D",
    ),
)
_search_trigger(
    "timesheets",
    ("coalesce(new.description, '')", "A"),
    (
        " || ' ' || ".join(
            (
                _related_name("employees", "employee_id"),
                _related_name("tasks", "task_id", "title"),
                _related_name("projects", "project_id"),
            )
        ),
        "D",
    ),
)
_search_trigger(
    "expenses",
    ("coalesce(new.expense_number, '')", "A"),
    (
        "new.status::text || ' ' || new.category::text "
        "|| ' ' || coalesce(new.description, '')",
        "B",
    ),
    ("coalesce(new.notes, '')", "C"),
    (
        " || ' ' || ".join(
            (
                _related_name("employees", "employee_id"),
                _related_name("projects", "project_id"),
                _related_name("employees", "approved_by"),
            )
        ),
        "D",
    ),
)
_search_trigger(
    "expense_lines",
    ("coalesce(new.description, '')", "A"),
)

# Renaming a referenced row must reach the vectors that folded its old name
# in; each entry mirrors a `_related_name` reference above.
_restamp_dependents_on_rename(
    "departments",
    "name",
    [
        ("departments", "parent_id"),
        ("employees", "department_id"),
        ("projects", "department_id"),
    ],
)
_restamp_dependents_on_rename(
    "employees",
    "name",
    [
        ("leave_requests", "employee_id"),
        ("leave_requests", "approver_id"),
        ("tasks", "assigned_to"),
        ("timesheets", "employee_id"),
        ("expenses", "employee_id"),
        ("expenses", "approved_by"),
    ],
)
_restamp_dependents_on_rename(
    "projects",
    "name",
    [
        ("tasks", "project_id"),
        ("timesheets", "project_id"),
        ("expenses", "project_id"),
    ],
)
_restamp_dependents_on_rename("tasks", "title", [("timesheets", "task_id")])


# ── Rename-restamp outbox drain ──────────────────────────────────────────────
# `process_restamp_jobs` drains the outbox: for every job it pages the dependent table
# in `RESTAMP_CHUNK_SIZE` rows (each page its own transaction) and issues a no-op UPDATE
# on `search_vector`, which the table's own refresh trigger turns into a real recompute.
# Run event-driven by `celery_app.py`'s `process_search_restamp_jobs` task (no Beat
# schedule), enqueued by `SearchRestampSubscriber` after every admin edit/import.

# Rows touched per committed batch. Bounds how long any single transaction
# holds locks on the dependent table, at the cost of more round trips for a
# large rename.
RESTAMP_CHUNK_SIZE = int(os.getenv("SEARCH_RESTAMP_CHUNK_SIZE", "2000"))


def _restamp_dependent_table(
    session: Session, table: str, fk: str, source_id: int
) -> None:
    """Touch every row of `table` where `fk == source_id`, `RESTAMP_CHUNK_SIZE`
    at a time, committing each page so no single transaction holds a lock on
    more than a page's worth of rows."""
    last_id = 0
    while True:
        page = (
            session.execute(
                text(
                    f"UPDATE {table} SET search_vector = search_vector "
                    f"WHERE id IN ("
                    f"SELECT id FROM {table} "
                    f"WHERE {fk} = :source_id AND id > :last_id "
                    f"ORDER BY id LIMIT :chunk_size"
                    f") RETURNING id"
                ),
                {
                    "source_id": source_id,
                    "last_id": last_id,
                    "chunk_size": RESTAMP_CHUNK_SIZE,
                },
            )
            .scalars()
            .all()
        )
        session.commit()
        if len(page) < RESTAMP_CHUNK_SIZE:
            return
        last_id = max(page)


async def process_restamp_jobs() -> None:
    """Drain every pending `SearchRestampJob`. Declared `async def` to match
    the interface `celery_app.py` drives every DB-touching task through (see
    its module docstring); the work itself is plain sync ORM/SQL."""
    with Session(engine) as session:
        jobs = session.scalars(select(SearchRestampJob)).all()
        for job in jobs:
            for dep_table, fk in RESTAMP_DEPENDENTS.get(job.kind, []):
                _restamp_dependent_table(session, dep_table, fk, job.source_id)
            session.delete(job)
            session.commit()


def trigger_search_restamp() -> None:
    """Ask Celery to drain the search-restamp outbox now instead of waiting out Beat's
    schedule. Imports `celery_app` lazily, same as `cache.py`'s `trigger_dashboard_refresh`."""
    from .celery_app import process_search_restamp_jobs

    process_search_restamp_jobs.delay()


class SearchRestampSubscriber(AdminEventSubscriber):
    """Subscribed admin-wide: `admin.events.subscribe(SearchRestampSubscriber())`. Only
    edits and imports can rename something, so unlike `DashboardCacheSubscriber` this
    doesn't listen for create/delete."""

    @on(AdminEvent.AFTER_EDIT_COMMITTED)
    async def restamp_on_edit(self, ctx: AfterEditContext) -> None:
        trigger_search_restamp()

    @on(AdminEvent.AFTER_IMPORT)
    async def restamp_on_import(self, ctx: AfterImportContext) -> None:
        trigger_search_restamp()
