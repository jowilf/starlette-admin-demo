from typing import Any

from starlette.requests import Request
from starlette_admin.contrib.odmantic import ModelView

from app.odmantic.models import Author


class AuthorView(ModelView):
    exclude_fields_from_list = [Author.addresses]

    def can_delete(self, request: Request) -> bool:
        return False

    async def repr(self, obj: Any, request: Request) -> str:
        assert isinstance(obj, Author)
        return obj.first_name + " " + obj.last_name
