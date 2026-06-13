"""Database models: User, Product, Order, Session."""

from datetime import datetime
from enum import Enum
from utils.db import query, execute


class UserRole(Enum):
    ADMIN = "admin"
    CUSTOMER = "customer"
    MERCHANT = "merchant"


class User:
    """Represents a registered user."""

    def __init__(self, id: int, email: str, name: str, role: UserRole,
                 password_hash: str, stripe_customer_id: str):
        self.id = id
        self.email = email
        self.name = name
        self.role = role
        self.password_hash = password_hash
        self.stripe_customer_id = stripe_customer_id

    @classmethod
    def find_by_email(cls, email: str):
        row = query("SELECT * FROM users WHERE email = ?", (email,))
        return cls._from_row(row) if row else None

    @classmethod
    def find_by_id(cls, user_id: int):
        row = query("SELECT * FROM users WHERE id = ?", (user_id,))
        return cls._from_row(row) if row else None

    def save(self):
        execute("UPDATE users SET password_hash = ?, stripe_customer_id = ? WHERE id = ?",
                (self.password_hash, self.stripe_customer_id, self.id))

    @staticmethod
    def _from_row(row):
        return User(
            id=row["id"], email=row["email"], name=row["name"],
            role=UserRole(row["role"]), password_hash=row["password_hash"],
            stripe_customer_id=row["stripe_customer_id"],
        )


class Product:
    """Represents a purchasable product."""

    def __init__(self, id: int, name: str, price_cents: int, stock: int):
        self.id = id
        self.name = name
        self.price_cents = price_cents
        self.stock = stock

    @classmethod
    def find_by_id(cls, product_id: int):
        row = query("SELECT * FROM products WHERE id = ?", (product_id,))
        return cls._from_row(row) if row else None

    @staticmethod
    def _from_row(row):
        return Product(id=row["id"], name=row["name"],
                       price_cents=row["price_cents"], stock=row["stock"])


class Order:
    """Represents a customer order."""

    def __init__(self, id: int, user_id: int, items: list, total_cents: int,
                 currency: str, status: str, transaction_id: str = ""):
        self.id = id
        self.user_id = user_id
        self.items = items
        self.total_cents = total_cents
        self.currency = currency
        self.status = status
        self.transaction_id = transaction_id

    @classmethod
    def create(cls, user_id: int, items: list, total_cents: int, currency: str = "usd"):
        order_id = execute(
            "INSERT INTO orders (user_id, total_cents, currency, status) VALUES (?, ?, ?, ?)",
            (user_id, total_cents, currency, "pending"),
        )
        return cls(id=order_id, user_id=user_id, items=items,
                   total_cents=total_cents, currency=currency, status="pending")

    def save(self):
        execute("UPDATE orders SET status = ?, transaction_id = ? WHERE id = ?",
                (self.status, self.transaction_id, self.id))
