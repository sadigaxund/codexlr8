"""Stripe API integration for processing payments."""

import stripe
from utils.config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET

stripe.api_key = STRIPE_SECRET_KEY


class PaymentResult:
    """Represents the outcome of a payment attempt."""
    def __init__(self, success: bool, transaction_id: str, error: str = ""):
        self.success = success
        self.transaction_id = transaction_id
        self.error = error


def charge_customer(amount_cents: int, currency: str, customer_id: str) -> PaymentResult:
    """Charge a customer's saved payment method via Stripe."""
    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency=currency,
            customer=customer_id,
            confirm=True,
        )
        return PaymentResult(
            success=intent.status == "succeeded",
            transaction_id=intent.id,
        )
    except stripe.error.StripeError as e:
        return PaymentResult(success=False, transaction_id="", error=str(e))


def create_customer(email: str, name: str) -> str:
    """Create a new Stripe customer and return the customer ID."""
    customer = stripe.Customer.create(email=email, name=name)
    return customer.id


def verify_webhook(payload: bytes, signature: str) -> dict:
    """Verify a Stripe webhook event signature."""
    return stripe.Webhook.construct_event(
        payload, signature, STRIPE_WEBHOOK_SECRET
    )
