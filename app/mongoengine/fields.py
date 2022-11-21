from typing import Any

from starlette.requests import Request
from starlette_admin import DecimalField, RequestAction


class MoneyField(DecimalField):
    """
    Example of custom field to send price formatted value for
    Listing page, detail page and select2 AJAX request.
    """

    async def serialize_value(
        self, request: Request, value: Any, action: RequestAction
    ) -> Any:
        if action != RequestAction.EDIT:
            """Return formatted value for API, LIST and VIEW,"""
            return f"${value}"
        return await super().serialize_value(request, value, action)
