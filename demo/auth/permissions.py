"""Permission decorators and auth middleware."""

from functools import wraps
from utils.db import get_session
from models.user import User, UserRole


def require_auth(func):
    """Decorator: require a valid session token to access the endpoint."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        token = _extract_token(kwargs.get("request"))
        if not token:
            raise AuthError("No authentication token provided")
        session = get_session(token)
        if not session or session.is_expired():
            raise AuthError("Invalid or expired token")
        kwargs["user"] = User.find_by_id(session.user_id)
        return func(*args, **kwargs)
    return wrapper


def require_role(role: UserRole):
    """Decorator: require the authenticated user to have a specific role."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "user" not in kwargs:
                raise AuthError("require_auth must be applied first")
            user = kwargs["user"]
            if user.role != role:
                raise AuthError(f"Required role: {role.value}")
            return func(*args, **kwargs)
        return wrapper
    return decorator


def _extract_token(request) -> str | None:
    """Extract the Bearer token from the request headers."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:]
    return None
