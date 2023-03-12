from mongoengine import connect
from starlette_admin import DropDown
from starlette_admin import I18nConfig
from starlette_admin.contrib.mongoengine import Admin
from starlette_admin.views import Link

from app.config import config
from app.mongoengine.models import Category, Product
from app.mongoengine.views import CategoryView, ProductView

__all__ = ["admin", "connection"]

connection = connect(host=config.mongo_uri)

admin = Admin(
    "MongoEngine Admin",
    base_url="/admin/mongoengine",
    route_name="admin-mongoengine",
    logo_url="https://preview.tabler.io/static/logo-white.svg",
    login_logo_url="https://preview.tabler.io/static/logo.svg",
    templates_dir="templates/admin/mongoengine",
    i18n_config=I18nConfig(language_switcher=["en", "fr"]),
)

admin.add_view(
    DropDown(
        label="Store",
        icon="fa fa-store",
        views=[ProductView(Product), CategoryView(Category, label="Categories")],
    )
)
admin.add_view(
    Link(
        "StarletteAdmin Docs",
        url="https://jowilf.github.io/starlette-admin/",
        icon="fa fa-book",
        target="_blank",
    )
)
admin.add_view(Link(label="Go Back to Home", icon="fa fa-link", url="/"))
