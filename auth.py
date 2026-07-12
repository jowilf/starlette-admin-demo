"""Basic username/password authentication for the admin.

Two hardcoded users: `admin` (full access) and `reader` (read-only, enforced
in `views.ModelView.can_create/can_edit/can_delete`). Both use "password" as
their password.
"""

from dataclasses import dataclass

from starlette.requests import Request
from starlette_admin.auth.base import AdminUser
from starlette_admin.auth.password import AuthProvider
from starlette_admin.exceptions import LoginFailed


@dataclass
class User:
    username: str
    password: str
    role: str


@dataclass
class RoleAdminUser(AdminUser):
    role: str = "reader"


USERS = {
    "admin": User(username="admin", password="password", role="admin"),
    "reader": User(username="reader", password="password", role="reader"),
}


class MyAuthProvider(AuthProvider):
    async def login(
        self,
        username: str,
        password: str,
        remember_me: bool,
        request: Request,
    ) -> None:
        user = USERS.get(username)
        if user is None or user.password != password:
            raise LoginFailed("Invalid username or password")
        request.session.update({"username": username})

    async def logout(self, request: Request) -> None:
        request.session.clear()

    async def authenticate(self, request: Request) -> AdminUser | None:
        user = USERS.get(request.session.get("username"))
        if user is None:
            return None
        return RoleAdminUser(username=user.username, role=user.role)
