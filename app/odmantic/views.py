from starlette.requests import Request
from starlette_admin.contrib.odmantic import ModelView

from app.odmantic.models import Author


class AuthorView(ModelView):
    exclude_fields_from_list = [Author.addresses]
    fields_default_sort = [Author.first_name]

    def can_delete(self, request: Request) -> bool:
        return False
