import enum
from datetime import datetime
from typing import List, Optional, Union

from pydantic import EmailStr
from sqlalchemy import JSON, Column, DateTime, Enum, Text
from sqlalchemy_file import File, ImageField
from sqlalchemy_file.validators import SizeValidator
from sqlmodel import Field, Relationship, SQLModel

from app.common import UploadFile


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"


class User(SQLModel, table=True):
    id: Optional[int] = Field(primary_key=True)
    full_name: str = Field(min_length=3, index=True)
    sex: Optional[str] = Field(
        sa_column=Column(Enum(Gender)), default=Gender.UNKNOWN, index=True
    )
    username: EmailStr = Field(index=True)
    avatar: Union[File, UploadFile, None] = Field(
        sa_column=Column(
            ImageField(
                upload_storage="user-avatar",
                thumbnail_size=(128, 128),
                validators=[SizeValidator(max_size="100k")],
            )
        )
    )

    posts: List["Post"] = Relationship(back_populates="publisher")
    comments: List["Comment"] = Relationship(back_populates="user")


class Post(SQLModel, table=True):
    id: Optional[int] = Field(primary_key=True)
    title: str = Field(min_length=3)
    content: str = Field(sa_column=Column(Text))
    tags: List[str] = Field(sa_column=Column(JSON))
    published_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )

    publisher_id: Optional[int] = Field(foreign_key="user.id")
    publisher: User = Relationship(back_populates="posts")

    comments: List["Comment"] = Relationship(back_populates="post")


class Comment(SQLModel, table=True):
    pk: Optional[int] = Field(primary_key=True)
    content: str = Field(sa_column=Column(Text), min_length=5)
    created_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )

    post_id: Optional[int] = Field(foreign_key="post.id")
    post: Post = Relationship(back_populates="comments")

    user_id: Optional[int] = Field(foreign_key="user.id")
    user: User = Relationship(back_populates="comments")
