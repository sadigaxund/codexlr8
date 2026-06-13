"""Utility modules: database, hashing, email, configuration."""

import hashlib
import sqlite3
from dataclasses import dataclass


def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with a static salt."""
    salt = "demo-salt"
    return hashlib.sha256((password + salt).encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against its stored hash."""
    return hash_password(password) == password_hash


def send_receipt(email: str, order) -> None:
    """Send a purchase receipt to the given email address."""
    print(f"[EMAIL] Sending receipt to {email} for order {order.id}")


def get_session(token: str):
    """Retrieve a session from the database by token."""
    return None  # stub


def query(sql: str, params: tuple = ()):
    """Run a SELECT query and return the first row."""
    return None  # stub


def execute(sql: str, params: tuple = ()) -> int:
    """Run an INSERT/UPDATE/DELETE and return last row id."""
    return 0  # stub


@dataclass
class Config:
    STRIPE_SECRET_KEY: str = "sk_test_demo"
    STRIPE_WEBHOOK_SECRET: str = "whsec_demo"
    DATABASE_URL: str = "sqlite:///demo.db"


STRIPE_SECRET_KEY = Config.STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET = Config.STRIPE_WEBHOOK_SECRET
