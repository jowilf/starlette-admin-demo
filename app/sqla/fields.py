from typing import Any

from markdown import markdown
from markupsafe import Markup
from starlette.requests import Request
from starlette_admin import RequestAction, TextAreaField, StringField

from app.sqla import User


class MarkdownField(TextAreaField):
    """
    Example of custom field to render markdown content on detail page
    """

    async def serialize_value(
        self, request: Request, value: Any, action: RequestAction
    ) -> Any:
        if action == RequestAction.DETAIL:
            return markdown(Markup.escape(value))
        return await super().serialize_value(request, value, action)


class CommentCounterField(StringField):
    """
    Example of field not tied to model attributes

    This fields will count the number of comments a user has made.

    It's important to exclude this fields from create and edit
    """

    async def parse_obj(self, request: Request, obj: Any) -> Any:
        assert isinstance(obj, User)
        return len(obj.comments)
