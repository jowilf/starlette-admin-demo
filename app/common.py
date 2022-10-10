from typing import Any, Callable, Dict, Iterable, Type

from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette_admin import DropDown
from starlette_admin.views import Link


class StarletteAdminDocumentation(Link):
    label = "StarletteAdmin Docs"
    url = "https://jowilf.github.io/starlette-admin/"
    target = "_blank"


class SQLAlchemyFileDocumentation(Link):
    label = "SQLAlchemy-file Docs"
    url = "https://github.com/jowilf/sqlalchemy-file"
    target = "_blank"


class GotoMongoAdmin(Link):
    label = "MongoEngine Admin"
    icon = "fa fa-link"
    url = "/admin/mongo"


class GotoSqlaAdmin(Link):
    label = "SQLAlchemy Admin"
    icon = "fa fa-link"
    url = "/admin/sqla"


class Resources(DropDown):
    label = "Resources"
    icon = "fa fa-book"
    views = [StarletteAdminDocumentation, SQLAlchemyFileDocumentation]


class UploadFile(StarletteUploadFile):
    """Need this to work with SQLModel"""

    @classmethod
    def __get_validators__(cls: Type["UploadFile"]) -> Iterable[Callable[..., Any]]:
        yield cls.validate

    @classmethod
    def validate(cls: Type["UploadFile"], v: Any) -> Any:
        if not isinstance(v, StarletteUploadFile):
            raise ValueError(f"Expected UploadFile, received: {type(v)}")
        return v

    @classmethod
    def __modify_schema__(cls, field_schema: Dict[str, Any]) -> None:
        field_schema.update({"type": "string", "format": "binary"})
