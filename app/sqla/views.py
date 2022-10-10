from typing import Any, Dict, Union

import markupsafe
from jinja2 import Template
from markdown import markdown
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response
from starlette.templating import Jinja2Templates
from starlette_admin import BaseField, CustomView, EmailField, TagsField
from starlette_admin.contrib.sqla import SQLModelView as ModelView
from starlette_admin.exceptions import FormValidationError

from app.sqla.models import Comment, Post, User


class UserView(ModelView, model=User):
    label = "Users"
    icon = "fa fa-users"
    page_size_options = [5, 10, 25, -1]
    fields = [
        "id",
        "full_name",
        EmailField("username"),
        "avatar",
        "posts",
        "comments",
    ]

    async def select2_result(self, obj: Any, request: Request) -> str:
        url = None
        if obj.avatar is not None:
            storage, file_id = obj.avatar.path.split("/")
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
        return Template(template_str, autoescape=True).render(obj=obj, url=url)

    async def select2_selection(self, obj: Any, request: Request) -> str:
        template_str = "<span>{{obj.full_name}}</span>"
        return Template(template_str, autoescape=True).render(obj=obj)

    async def repr(self, obj: Any, request: Request) -> str:
        return obj.full_name

    def can_delete(self, request: Request) -> bool:
        return False


class PostView(ModelView, model=Post):
    label = "Blog Posts"
    icon = "fa fa-blog"
    fields = [
        "id",
        "title",
        "content",
        TagsField("tags"),
        "published_at",
        "publisher",
        "comments",
    ]
    exclude_fields_from_list = ["content"]
    exclude_fields_from_create = [Post.published_at]
    exclude_fields_from_edit = [Post.published_at]
    detail_template = "post_detail.html"

    async def validate(self, request: Request, data: Dict[str, Any]) -> None:
        """Assert publisher is not None"""
        if data["publisher"] is None:
            raise FormValidationError({"publisher": "Can't add post without publisher"})
        return await super().validate(request, data)

    async def serialize_field_value(
            self, value: Any, field: BaseField, ctx: str, request: Request
    ) -> Union[Dict[str, Any], str, None]:
        if ctx == "VIEW" and field.name == "content":
            return markdown(markupsafe.escape(value))
        return await super().serialize_field_value(value, field, ctx, request)

    async def select2_result(self, obj: Any, request: Request) -> str:
        template_str = (
            "<span><strong>Title: </strong>{{obj.title}}, <strong>Publish by:"
            " </strong>{{obj.publisher.full_name}}</span>"
        )
        return Template(template_str, autoescape=True).render(
            obj=obj, fields=["id", "title"]
        )

    def can_delete(self, request: Request) -> bool:
        return False

    def can_edit(self, request: Request) -> bool:
        return request.state.user == "admin"


class CommentView(ModelView, model=Comment):
    label = "Comments"
    icon = "fa fa-comments"
    page_size = 5
    page_size_options = [5, 10]
    exclude_fields_from_create = ["created_at"]
    exclude_fields_from_edit = ["created_at"]
    searchable_fields = [Comment.content, Comment.created_at]
    sortable_fields = [Comment.pk, Comment.content, Comment.created_at]

    def is_accessible(self, request: Request) -> bool:
        return request.state.user == "admin"


class CustomIndexView(CustomView):
    label = "Home"
    icon = "fa fa-home"

    async def render(self, request: Request, templates: Jinja2Templates) -> Response:
        session: Session = request.state.session
        stmt1 = select(Post).limit(10).order_by(desc(Post.published_at))
        stmt2 = (
            select(User, func.count(Post.id).label("cnt"))
                .limit(5)
                .join(Post)
                .group_by(User.id)
                .order_by(desc("cnt"))
        )
        posts = session.execute(stmt1).scalars().all()
        users = session.execute(stmt2).scalars().all()
        return templates.TemplateResponse(
            "home.html", {"request": request, "posts": posts, "users": users}
        )
