from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette_admin import __version__ as starlette_admin_version

from app.config import config
from app.mongoengine import admin as admin_mongo
from app.odmantic import admin as admin_odm
from app.sqla import admin as admin_sqla


async def homepage(request):
    return Jinja2Templates("templates").TemplateResponse(
        "index.html", {"request": request, "config": config, "starlette_admin_version": starlette_admin_version}
    )


app = Starlette(
    routes=[
        Route("/", homepage),
        Mount("/statics", app=StaticFiles(directory="statics"), name="statics"),
    ]
)
admin_sqla.mount_to(app)
admin_mongo.mount_to(app)
admin_odm.mount_to(app)
