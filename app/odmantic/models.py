from enum import Enum
from typing import List, Optional

from odmantic import EmbeddedModel, Field, Model, Reference
from pydantic import EmailStr
from starlette.requests import Request


class Address(EmbeddedModel):
    street: str = Field(min_length=3)
    city: str = Field(min_length=3)
    state: Optional[str]
    zipcode: Optional[str]


class Author(Model):
    first_name: str = Field(min_length=3)
    last_name: str = Field(min_length=3)
    email: Optional[EmailStr]
    addresses: List[Address] = Field(default_factory=list)

    async def __admin_repr__(self, request: Request):
        return f"{self.last_name} {self.first_name}"


class BookFormat(str, Enum):
    Hardcover = "hardcover"
    Graphic = "graphic"
    Paperback = "paperback"
    Mass_market_paperback = "mass_market_paperback"


class Book(Model):
    title: str = Field(min_length=5)
    format: BookFormat
    year: int = Field(ge=1900, le=2022)
    awards: List[str] = Field(default_factory=list, min_length=3)
    author: Author = Reference()
