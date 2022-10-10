from typing import Any, Dict, Union

from starlette.requests import Request
from starlette_admin import BaseField, DropDown
from starlette_admin.contrib.mongoengine import ModelView

from app.mongoengine.models import Category, Product


class ProductView(ModelView, document=Product):
    page_size_options = [5, 10]
    label = "Products"

    async def serialize_field_value(
        self, value: Any, field: BaseField, action: str, request: Request
    ) -> Union[Dict[Any, Any], str, None]:
        if field.name == "price" and action != "EDIT":
            return f"${value}"
        return await super().serialize_field_value(value, field, action, request)

    def can_delete(self, request: Request) -> bool:
        return True


class CategoryView(ModelView, document=Category):
    label = "Categories"
    page_size = 5
    page_size_options = [5, 10]

    async def repr(self, obj: Any, request: Request) -> str:
        return obj.name

    def can_delete(self, request: Request) -> bool:
        return False


class Store(DropDown):
    label = "Store"
    icon = "fa fa-store"
    views = [ProductView, CategoryView]
