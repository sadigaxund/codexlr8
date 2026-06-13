"""User authentication: login, logout, session management, password reset."""

from models.user import User
from utils.hashing import verify_password, hash_password
from utils.db import get_session


def login(email: str, password: str) -> str:
    """Authenticate a user and return a JWT session token.

    Raises AuthError if credentials are invalid.
    """
    user = User.find_by_email(email)
    if not user or not verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password")
    return create_session(user.id)


def logout(session_token: str) -> None:
    """Invalidate a session token, logging the user out."""
    session = get_session(session_token)
    if session:
        session.revoke()


def reset_password(email: str, new_password: str) -> None:
    """Reset a user's password after email verification."""
    user = User.find_by_email(email)
    if not user:
        raise AuthError("User not found")
    user.password_hash = hash_password(new_password)
    user.save()


def create_session(user_id: int) -> str:
    """Create a new authenticated session for a user."""
    from models.session import Session
    return Session.create(user_id)


class AuthError(Exception):
    """Raised when authentication fails."""
    pass
