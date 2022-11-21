from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from app.config import config
from app.mongoengine import admin as admin_mongo
from app.odmantic import admin as admin_odm
from app.sqla import admin as admin_sqla


async def homepage(request):
    return Jinja2Templates("templates").TemplateResponse(
        "index.html", {"request": request}
    )


app = Starlette(
    routes=[
        Route("/", homepage),
        Mount("/statics", app=StaticFiles(directory="statics"), name="statics"),
    ],
    middleware=[Middleware(SessionMiddleware, secret_key=config.secret)],
)
admin_sqla.mount_to(app)
admin_mongo.mount_to(app)
admin_odm.mount_to(app)
