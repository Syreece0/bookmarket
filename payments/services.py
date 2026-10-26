"""Paystack integration.

An order is marked paid ONLY after the provider's verify endpoint (or a signature-verified webhook that
triggers the same verification) confirms status, amount, currency and reference. A browser redirect
to the callback URL is never treated as proof of payment.

Check Paystack's current documentation before going live: endpoints, header names, and fee fields can change.
"""
import hashlib
import hmac
import logging
import uuid

import requests
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core.money import from_minor_units, to_minor_units
from engagement.services import notify
from finance.services import allocate_order
from orders.models import Entitlement, Order

from .models import PaymentTransaction

log = logging.getLogger(__name__)
TIMEOUT = 20


class PaymentError(Exception):
    pass


def _headers():
    if not settings.PAYSTACK_SECRET_KEY:
        raise PaymentError("Payments are not configured yet. Please try again later.")
    return {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}


def initiate_payment(order, request):
    if order.currency not in settings.PAYMENT_SUPPORTED_CURRENCIES:
        raise PaymentError("This currency is not supported for payment yet.")
    reference = f"PAY-{uuid.uuid4().hex[:20].upper()}"
    txn = PaymentTransaction.objects.create(order=order, reference=reference, amount=order.total, currency=order.currency)
    payload = {
        "email": order.customer.email,
        "amount": to_minor_units(order.total),
        "currency": order.currency,
        "reference": reference,
        "callback_url": request.build_absolute_uri(reverse("payments:callback")),
        "metadata": {"order_reference": order.reference},
    }
    try:
        resp = requests.post(f"{settings.PAYSTACK_BASE_URL}/transaction/initialize", json=payload, headers=_headers(), timeout=TIMEOUT)
        data = resp.json()
    except (requests.RequestException, ValueError):
        txn.status, txn.failure_reason = PaymentTransaction.Status.FAILED, "Could not reach payment provider"
        txn.save(update_fields=["status", "failure_reason"])
        raise PaymentError("We could not reach the payment provider. Please try again.")
    if not resp.ok or not data.get("status"):
        txn.status, txn.failure_reason = PaymentTransaction.Status.FAILED, str(data.get("message", ""))[:240]
        txn.save(update_fields=["status", "failure_reason"])
        raise PaymentError("The payment provider rejected this request. Please try again.")
    return data["data"]["authorization_url"]


def verify_signature(raw_body: bytes, signature: str) -> bool:
    """Paystack signs the raw request body with HMAC-SHA512 using your secret key."""
    if not settings.PAYSTACK_SECRET_KEY or not signature:
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


def fetch_verification(reference):
    try:
        resp = requests.get(f"{settings.PAYSTACK_BASE_URL}/transaction/verify/{reference}", headers=_headers(), timeout=TIMEOUT)
        return resp.json()
    except (requests.RequestException, ValueError):
        raise PaymentError("Could not verify the payment right now.")


def finalize_payment(reference, verification=None):
    """Verify with the provider and, only if everything matches, mark the order paid.

    Returns the PaymentTransaction. Idempotent: calling it again for a paid order changes nothing."""
    verification = verification if verification is not None else fetch_verification(reference)
    data = (verification or {}).get("data") or {}

    with transaction.atomic():
        try:
            txn = PaymentTransaction.objects.select_for_update().select_related("order").get(reference=reference)
        except PaymentTransaction.DoesNotExist:
            raise PaymentError("Unknown payment reference.")
        order = Order.objects.select_for_update().get(pk=txn.order_id)
        if txn.status == PaymentTransaction.Status.SUCCESS and order.status == Order.Status.PAID:
            return txn  # duplicate notification: nothing to do

        txn.verification_payload = verification
        txn.verified_at = timezone.now()

        if not verification.get("status") or data.get("status") != "success":
            if data.get("status") in ("failed", "abandoned", "reversed"):
                txn.status = PaymentTransaction.Status.FAILED
                txn.failure_reason = str(data.get("gateway_response", ""))[:240]
                order.status = Order.Status.FAILED
                order.save(update_fields=["status"])
                notify(order.customer, "Payment failed", f"Your payment for order {order.reference} did not go through.", "/orders/")
            txn.save()
            return txn

        paid_amount = from_minor_units(data.get("amount", 0))
        if data.get("reference") != reference or paid_amount != txn.amount or data.get("currency") != txn.currency:
            txn.status = PaymentTransaction.Status.MISMATCH
            txn.failure_reason = "Provider amount, currency or reference did not match the order."
            txn.save()
            log.warning("Payment mismatch for %s", reference)
            return txn

        fee = from_minor_units(data.get("fees") or 0)
        txn.status = PaymentTransaction.Status.SUCCESS
        txn.provider_fee = fee
        txn.save()

        order.status = Order.Status.PAID
        order.paid_at = timezone.now()
        order.save(update_fields=["status", "paid_at"])
        for item in order.items.all():
            ent, created = Entitlement.objects.get_or_create(
                user=order.customer, book=item.book,
                defaults={"order_item": item, "source": Entitlement.Source.PURCHASE},
            )
            if not created and (ent.revoked_at is not None or ent.order_item_id is None):
                # Re-purchase after a refund, or a free copy upgraded to a purchase.
                ent.order_item, ent.revoked_at, ent.revoked_reason = item, None, ""
                ent.source = Entitlement.Source.PURCHASE
                ent.save()
        allocate_order(order, fee)
        notify(order.customer, "Purchase successful", f"Order {order.reference} is complete. Your books are in your library.", "/library/")
        for seller in {i.seller for i in order.items.select_related("seller")}:
            notify(seller, "You made a sale", f"A copy of your book was sold (order {order.reference}).", "/dashboard/")
        return txn
