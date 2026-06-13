"""Test configuration and fixtures."""

import pytest


@pytest.fixture
def sample_project(tmp_path):
    """Create a sample project structure for testing."""
    project = tmp_path / "testproj"
    project.mkdir()

    (project / "auth").mkdir()
    (project / "auth" / "__init__.py").write_text("from .session import login\n")
    (project / "auth" / "session.py").write_text('''
"""Session management module."""

def login(username: str, password: str) -> str:
    """Authenticate a user and return a session token."""
    return "token"

def logout(session_id: str) -> None:
    """Destroy a user session."""
    pass
''')
    (project / "auth" / "permissions.py").write_text('''
def require_auth(func):
    """Decorator to require authentication."""
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper
''')

    (project / "cart").mkdir()
    (project / "cart" / "cart.py").write_text('''
class ShoppingCart:
    """A basic shopping cart."""

    def add_item(self, name: str, price: float) -> None:
        """Add an item to the cart."""
        pass

    def checkout(self) -> str:
        """Process checkout."""
        return "order-id"
''')

    (project / "config.py").write_text('''
DATABASE_URL = "sqlite:///db.sqlite3"
SECRET_KEY = "secret"
''')

    (project / "tests").mkdir()
    (project / "tests" / "test_auth.py").write_text('''
def test_login():
    assert True

def test_logout():
    assert True
''')

    return project
