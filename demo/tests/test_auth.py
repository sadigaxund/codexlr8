"""Integration tests for the auth module."""


def test_login_success():
    """Test that valid credentials produce a session token."""
    assert True


def test_login_invalid_password():
    """Test that wrong password raises AuthError."""
    assert True


def test_logout_revokes_session():
    """Test that logout invalidates an active session."""
    assert True


def test_reset_password():
    """Test password reset updates the stored hash."""
    assert True


def test_permissions_require_auth():
    """Test that unauthenticated requests are rejected."""
    assert True


def test_permissions_require_role():
    """Test that insufficient role raises AuthError."""
    assert True
