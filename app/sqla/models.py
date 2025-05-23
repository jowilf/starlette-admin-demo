import enum
from datetime import datetime

from fastapi import UploadFile
from jinja2 import Template
from pydantic import ConfigDict, EmailStr, field_validator
from sqlalchemy import JSON, Column, DateTime, Enum, Text
from sqlalchemy_file import File, ImageField
from sqlalchemy_file.validators import SizeValidator
from sqlmodel import Field, Relationship, SQLModel
from starlette.requests import Request


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"


class User(SQLModel, table=True):
    id: int | None = Field(None, primary_key=True)
    full_name: str = Field(min_length=3, index=True)
    sex: str | None = Field(
        sa_column=Column(Enum(Gender), index=True),
        default=Gender.UNKNOWN,
    )
    username: EmailStr = Field(index=True)
    avatar: File | UploadFile | None = Field(
        None,
        sa_column=Column(
            ImageField(
                upload_storage="user-avatar",
                thumbnail_size=(128, 128),
                validators=[SizeValidator(max_size="100k")],
            )
        ),
    )

    posts: list["Post"] = Relationship(back_populates="publisher")
    comments: list["Comment"] = Relationship(back_populates="user")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def __admin_repr__(self, request: Request):
        return self.full_name

    async def __admin_select2_repr__(self, request: Request) -> str:
        url = None
        if self.avatar is not None:
            storage, file_id = self.avatar.path.split("/")
            url = request.url_for(
                request.app.state.ROUTE_NAME + ":api:file",
                storage=storage,
                file_id=file_id,
            )
        template_str = (
            '<div class="d-flex align-items-center"><span class="me-2 avatar'
            ' avatar-xs"{% if url %} style="background-image:'
            ' url({{url}});--tblr-avatar-size: 1.5rem;{%endif%}">{% if not url'
            " %}obj.full_name[:2]{%endif%}</span>{{obj.full_name}} <div>"
        )
        return Template(template_str, autoescape=True).render(obj=self, url=url)

    @field_validator("full_name", mode="before")
    @classmethod
    def validate_full_name(cls, value):
        parts = value.split()

        # Check if there are exactly two parts (first name and last name)
        if len(parts) != 2:
            raise ValueError(
                "Full name should contain exactly two parts separated by a single space. Example: 'John Doe'"
            )

        # Check if both parts contain only alphabetic characters
        if not all(part.isalpha() for part in parts):
            raise ValueError("Each part of the full name should contain only alphabetic characters.")

        return value


class Post(SQLModel, table=True):
    id: int | None = Field(primary_key=True)
    title: str = Field(min_length=3)
    content: str = Field(sa_column=Column(Text))
    tags: list[str] = Field(sa_column=Column(JSON), min_items=1, min_length=2)
    published_at: datetime | None = Field(sa_column=Column(DateTime(timezone=True), default=datetime.utcnow))

    publisher_id: int | None = Field(foreign_key="user.id")
    publisher: User = Relationship(back_populates="posts")

    comments: list["Comment"] = Relationship(back_populates="post")

    async def __admin_select2_repr__(self, request: Request) -> str:
        template_str = (
            "<span><strong>Title: </strong>{{obj.title}}, <strong>Publish by:"
            " </strong>{{obj.publisher.full_name}}</span>"
        )
        return Template(template_str, autoescape=True).render(obj=self)


class Comment(SQLModel, table=True):
    pk: int | None = Field(primary_key=True)
    content: str = Field(sa_column=Column(Text), min_length=5)
    created_at: datetime | None = Field(sa_column=Column(DateTime(timezone=True), default=datetime.utcnow))

    post_id: int | None = Field(foreign_key="post.id")
    post: Post = Relationship(back_populates="comments")

    user_id: int | None = Field(foreign_key="user.id")
    user: User = Relationship(back_populates="comments")
