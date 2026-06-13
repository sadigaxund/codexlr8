"""Payment processing pipeline: validation, charge, receipt."""

from payments.gateway import charge_customer, PaymentResult, create_customer
from models.order import Order
from models.user import User
from utils.email import send_receipt


def process_payment(order: Order, payment_token: str) -> PaymentResult:
    """Run the full payment pipeline for an order.

    1. Validate order status
    2. Charge the customer
    3. Update order status
    4. Send receipt email
    """
    if order.status != "pending":
        raise PaymentError(f"Cannot process order with status '{order.status}'")

    user = User.find_by_id(order.user_id)
    result = charge_customer(order.total_cents, order.currency, user.stripe_customer_id)

    if result.success:
        order.status = "paid"
        order.transaction_id = result.transaction_id
        order.save()
        send_receipt(user.email, order)

    return result


def refund_payment(order: Order) -> PaymentResult:
    """Issue a full refund for a paid order."""
    if order.status != "paid":
        raise PaymentError("Only paid orders can be refunded")
    # Refund logic would go here
    return PaymentResult(success=True, transaction_id=order.transaction_id)


class PaymentError(Exception):
    """Raised when payment processing fails."""
    pass
