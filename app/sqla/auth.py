from starlette.requests import Request
from starlette.responses import Response
from starlette_admin.auth import AuthProvider
from starlette_admin.exceptions import FormValidationError, LoginFailed


class MyAuthProvider(AuthProvider):
    """
    This is for demo purpose, it's not a better
    way to validate user credentials
    """

    async def login(
        self,
        username: str,
        password: str,
        remember_me: bool,
        request: Request,
        response: Response,
    ) -> Response:
        if len(username) < 3:
            """Form data validation"""
            raise FormValidationError(
                {"username": "Ensure username has at least 03 characters"}
            )
        if username in ["admin", "demo"] and password == "password":
            request.session.update({"username": username})
            return response
        raise LoginFailed("Invalid username or password")

    async def is_authenticated(self, request) -> bool:
        if request.session.get("username", None) in ["admin", "demo"]:
            request.state.user = request.session["username"]
            return True
        return False

    async def logout(self, request: Request, response: Response) -> Response:
        request.session.clear()
        return response
