"""Shopping cart and checkout orchestration."""

from models.product import Product
from models.order import Order
from payments.processor import process_payment
from utils.db import get_cart


class Cart:
    """A user's shopping cart with items and checkout logic."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.items: list[tuple[Product, int]] = []

    def add_item(self, product: Product, quantity: int = 1) -> None:
        """Add a product to the cart, or increase quantity if already present."""
        if product.stock < quantity:
            raise CartError(f"Not enough stock for {product.name}")
        for i, (p, q) in enumerate(self.items):
            if p.id == product.id:
                self.items[i] = (p, q + quantity)
                return
        self.items.append((product, quantity))

    def remove_item(self, product_id: int) -> None:
        """Remove a product entirely from the cart."""
        self.items = [(p, q) for p, q in self.items if p.id != product_id]

    def total_cents(self) -> int:
        """Calculate total cart value in cents."""
        return sum(p.price_cents * q for p, q in self.items)

    def checkout(self, payment_token: str) -> Order:
        """Convert the cart into an order and process payment."""
        if not self.items:
            raise CartError("Cart is empty")
        order = Order.create(
            user_id=self.user_id,
            items=[(p.id, q) for p, q in self.items],
            total_cents=self.total_cents(),
        )
        result = process_payment(order, payment_token)
        if not result.success:
            raise CartError(f"Payment failed: {result.error}")
        return order


class CartError(Exception):
    """Raised when a cart operation fails."""
    pass
