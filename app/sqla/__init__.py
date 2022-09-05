import os

from libcloud.storage.providers import get_driver
from libcloud.storage.types import Provider
from sqlalchemy_file.storage import StorageManager
from sqlmodel import create_engine
from starlette_admin.contrib.sqla import Admin

from app.common import GotoMongoAdmin, Resources
from app.config import config
from app.sqla.auth import MyAuthProvider
from app.sqla.views import CommentView, CustomIndexView, PostView, UserView

__all__ = ["engine", "admin"]

# Configure Storage
os.makedirs(f"{config.upload_dir}/avatars", 0o777, exist_ok=True)
container = get_driver(Provider.LOCAL)(config.upload_dir).get_container("avatars")
StorageManager.add_storage("user-avatar", container)

engine = create_engine(config.engine)
admin = Admin(
    engine,
    title="SQLModel Admin",
    base_url="/admin-sqla",
    route_name="admin-sqla",
    templates_dir="templates/admin-sqla",
    logo_url="https://preview.tabler.io/static/logo-white.svg",
    login_logo_url="https://preview.tabler.io/static/logo.svg",
    index_view=CustomIndexView,
    auth_provider=MyAuthProvider(login_path="/sign-in", logout_path="/sign-out"),
)

admin.add_view(UserView)
admin.add_view(PostView)
admin.add_view(CommentView)
admin.add_view(Resources)
admin.add_view(GotoMongoAdmin)
