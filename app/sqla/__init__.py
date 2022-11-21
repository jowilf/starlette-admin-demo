import os
from typing import Optional

from libcloud.storage.providers import get_driver
from libcloud.storage.types import Provider
from sqlalchemy_file.storage import StorageManager
from sqlmodel import create_engine
from starlette.requests import Request
from starlette_admin import DropDown
from starlette_admin.contrib.sqla import Admin as BaseAdmin
from starlette_admin.views import Link

from app.config import config
from app.sqla.auth import MyAuthProvider
from app.sqla.models import Comment, Post, User
from app.sqla.views import CommentView, HomeView, PostView, UserView

__all__ = ["engine", "admin"]

# Save avatar to local Storage
os.makedirs(f"{config.upload_dir}/avatars", 0o777, exist_ok=True)
container = get_driver(Provider.LOCAL)(config.upload_dir).get_container("avatars")
StorageManager.add_storage("user-avatar", container)

engine = create_engine(config.sqla_engine)


class Admin(BaseAdmin):
    def custom_render_js(self, request: Request) -> Optional[str]:
        return request.url_for("statics", path="js/custom_render.js")


admin = Admin(
    engine,
    title="SQLModel Admin",
    base_url="/admin/sqla",
    route_name="admin-sqla",
    templates_dir="templates/admin/sqla",
    logo_url="https://preview.tabler.io/static/logo-white.svg",
    login_logo_url="https://preview.tabler.io/static/logo.svg",
    index_view=HomeView(label="Home", icon="fa fa-home"),
    auth_provider=MyAuthProvider(login_path="/sign-in", logout_path="/sign-out"),
)

admin.add_view(UserView(User, icon="fa fa-users"))
admin.add_view(PostView(Post, label="Blog Posts", icon="fa fa-blog"))
admin.add_view(CommentView(Comment, icon="fa fa-comments"))
admin.add_view(
    DropDown(
        "Resources",
        icon="fa fa-book",
        views=[
            Link(
                "StarletteAdmin Docs",
                url="https://jowilf.github.io/starlette-admin/",
                target="_blank",
            ),
            Link(
                "SQLAlchemy-file Docs",
                url="https://jowilf.github.io/sqlalchemy-file/",
                target="_blank",
            ),
        ],
    )
)
admin.add_view(Link(label="Go Back to Home", icon="fa fa-link", url="/"))
