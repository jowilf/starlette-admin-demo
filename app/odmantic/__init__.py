from motor.motor_asyncio import AsyncIOMotorClient
from odmantic.engine import AIOEngine
from starlette_admin import I18nConfig
from starlette_admin.contrib.odmantic import Admin, ModelView
from starlette_admin.views import Link

from app.config import config
from app.odmantic.models import Author, Book

__all__ = ["admin", "engine"]

from app.odmantic.views import AuthorView

engine = AIOEngine(
    client=AsyncIOMotorClient(config.mongo_uri), database=config.mongo_db
)
admin = Admin(
    engine,
    title="ODMantic Admin",
    base_url="/admin/odmantic",
    route_name="admin-odmantic",
    logo_url="https://preview.tabler.io/static/logo-white.svg",
    login_logo_url="https://preview.tabler.io/static/logo.svg",
    templates_dir="templates/admin/odmantic",
    i18n_config=I18nConfig(default_locale="fr", language_switcher=["fr", "en"]),
)

admin.add_view(AuthorView(Author, icon="fa fa-users"))
admin.add_view(ModelView(Book, icon="fa fa-book"))
admin.add_view(Link(label="Go Back to Home", icon="fa fa-link", url="/"))
