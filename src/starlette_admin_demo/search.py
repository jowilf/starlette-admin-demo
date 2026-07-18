"""Full-text search support built on sqlalchemy-searchable and Postgres.

Each model's weighted `search_vector` column is kept up to date by a database trigger from
`make_searchable`, and the `@vectorizer` functions below combine sibling columns that share
a weight so ranking accounts for phrase adjacency.
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


# Configures mappers now so make_searchable's DDL listeners are registered before schema creation runs.
configure_mappers()


def fts_match(model: Any, term: str) -> Any:
    """WHERE clause matching `term` against `model`'s search_vector."""
    term = term.strip()
    if not term:
        return false()
    vector = inspect_search_vectors(model)[0]
    # Postgres won't implicitly cast a bound parameter to `regconfig`, so it must be inlined as a literal.
    regconfig = literal_column(f"'{search_manager.options.regconfig}'")
    return vector.bool_op("@@")(func.parse_websearch(regconfig, term))
