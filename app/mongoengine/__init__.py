from mongoengine import connect
from starlette_admin.contrib.mongoengine import Admin

from app.common import GotoSqlaAdmin, Resources
from app.config import config
from app.mongoengine.views import CategoryView, ProductView, Store

__all__ = ["admin", "connection"]

connection = connect(host=config.mongo_host)

admin = Admin(
    "MongoEngine Admin",
    base_url="/admin-mongo",
    route_name="admin-mongo",
    logo_url="https://preview.tabler.io/static/logo-white.svg",
    login_logo_url="https://preview.tabler.io/static/logo.svg",
    templates_dir="templates/admin-mongo",
)

admin.add_view(Store)
admin.add_view(Resources)
admin.add_view(GotoSqlaAdmin)
