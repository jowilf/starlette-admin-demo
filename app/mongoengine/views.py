from typing import Any

from starlette.requests import Request
from starlette_admin.contrib.mongoengine import ModelView

from app.mongoengine.fields import MoneyField
from app.mongoengine.models import Product


class ProductView(ModelView):
    fields = [
        "id",
        "title",
        "description",
        MoneyField(
            "price",
            label="Price (USD)",
            help_text="Product price in dollars (US)",
        ),
        "dimension",
        "image",
        "manual",
        "created_at",
        "category",
    ]
    exclude_fields_from_list = [Product.description]
    exclude_fields_from_create = ["created_at"]
    exclude_fields_from_edit = ["created_at"]


class CategoryView(ModelView):
    async def repr(self, obj: Any, request: Request) -> str:
        return obj.name

    def can_delete(self, request: Request) -> bool:
        return False
