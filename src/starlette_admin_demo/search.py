"""Everything behind the admin's search bars: sqlalchemy-searchable on top of Postgres
full-text search.

Every model in models.py declares its own `search_vector` TSVectorType column, weighted
(A > B > C > D) so `ts_rank`/`ts_rank_cd` ordering stays meaningful; `make_searchable`
(models.py, right after `Base`) is what turns those columns into a BEFORE INSERT OR
UPDATE trigger and a GIN index, created automatically once schema DDL runs - no hand-
rolled DDL needed. Search only ever matches a row's own columns - never a related
row's (e.g. an Employee's department name isn't searchable through the Employee view).

A few of those columns still need a `@vectorizer` below: a plain `TSVectorType` can only
concatenate columns independently, one `to_tsvector` call each, so two same-row columns
sharing a weight (e.g. an enum's `status` and `priority`) would rank phrase-adjacency
oddly if left separate. Each vectorizer instead returns the raw combined SQL for its
weight group, evaluated inside the row's own trigger; the sibling column it folds in is
dropped from the model's `TSVectorType(...)` column list so it isn't double-counted.
"""

from typing import Any

from sqlalchemy import false, func, literal_column, text
from sqlalchemy.orm import configure_mappers
from sqlalchemy_searchable import inspect_search_vectors, search_manager, vectorizer

from .models import Employee, Expense, LeaveRequest, Project, Task


@vectorizer(Employee.email)
def _employee_email_tokens(column: Any) -> Any:
    # Splits on '@'/'.' so "doe" matches john.doe@acme.com.
    return text("translate(coalesce(new.email, ''), '@.', '  ')")


@vectorizer(LeaveRequest.type)
def _leave_request_type_status(column: Any) -> Any:
    return text("new.type::text || ' ' || new.status::text")


@vectorizer(Project.name)
def _project_name_slug(column: Any) -> Any:
    return text("coalesce(new.name, '') || ' ' || coalesce(new.slug, '')")


@vectorizer(Project.status)
def _project_status_priority(column: Any) -> Any:
    return text("new.status::text || ' ' || new.priority::text")


@vectorizer(Task.status)
def _task_status_priority(column: Any) -> Any:
    return text("new.status::text || ' ' || new.priority::text")


@vectorizer(Expense.status)
def _expense_status_category_description(column: Any) -> Any:
    return text(
        "new.status::text || ' ' || new.category::text "
        "|| ' ' || coalesce(new.description, '')"
    )


# Forces mapper configuration (and thus make_searchable's DDL-listener setup, which
# only runs on the "after_configured" event) right now, rather than leaving it to
# whenever the app happens to issue its first ORM query - schema creation must not
# race ahead of it.
configure_mappers()


def fts_match(model: Any, term: str) -> Any:
    """WHERE clause matching `term` against `model`'s search_vector."""
    term = term.strip()
    if not term:
        return false()
    vector = inspect_search_vectors(model)[0]
    # regconfig must be an unknown-typed literal, not a bound parameter - passed as
    # one, Postgres won't implicitly cast it to the `regconfig` type parse_websearch
    # expects.
    regconfig = literal_column(f"'{search_manager.options.regconfig}'")
    return vector.bool_op("@@")(func.parse_websearch(regconfig, term))
