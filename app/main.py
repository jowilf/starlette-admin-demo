from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from app.config import config
from app.mongoengine import admin as admin_mongo
from app.sqla import admin as admin_sqla


async def homepage(request):
    return Jinja2Templates("templates").TemplateResponse(
        "index.html", {"request": request}
    )


app = Starlette(
    routes=[Route("/", homepage)],
    middleware=[Middleware(SessionMiddleware, secret_key=config.secret)],
)
admin_sqla.mount_to(app)
admin_mongo.mount_to(app)
