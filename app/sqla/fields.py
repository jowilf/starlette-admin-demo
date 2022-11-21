from typing import Any

from markdown import markdown
from markupsafe import Markup
from starlette.requests import Request
from starlette_admin import RequestAction, TextAreaField


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
