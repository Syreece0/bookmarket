import hashlib
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from orders.models import Order

from .models import PaymentTransaction, PaymentWebhookEvent
from .services import PaymentError, finalize_payment, verify_signature

log = logging.getLogger(__name__)


@login_required
def callback(request):
    """Where the customer's browser lands after paying. This is NOT proof of payment:
    we ask the provider to confirm the transaction before changing anything."""
    reference = request.GET.get("reference") or request.GET.get("trxref") or ""
    txn = PaymentTransaction.objects.select_related("order").filter(reference=reference, order__customer=request.user).first()
    if not txn:
        messages.error(request, "We could not find that payment.")
        return redirect("orders:order_list")
    try:
        txn = finalize_payment(reference)
    except PaymentError:
        messages.warning(request, "We could not confirm your payment yet. If you were charged, your books will appear shortly.")
        return redirect("orders:order_detail", reference=txn.order.reference)
    if txn.status == PaymentTransaction.Status.SUCCESS:
        request.session["cart"] = []
        messages.success(request, "Payment confirmed. Your books are ready in your library.")
        return redirect("library:home")
    messages.error(request, "Your payment was not completed. You have not been charged for this order.")
    return redirect("orders:cart")


@csrf_exempt  # Authenticated by HMAC signature instead of a CSRF token.
@require_POST
def webhook(request):
    raw = request.body
    if not verify_signature(raw, request.headers.get("x-paystack-signature", "")):
        return HttpResponseBadRequest("invalid signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        return HttpResponseBadRequest("invalid json")
    event_type = str(payload.get("event", ""))[:60]
    data = payload.get("data") or {}
    key = f"{event_type}:{data.get('reference') or data.get('id') or hashlib.sha256(raw).hexdigest()}"
    try:
        event = PaymentWebhookEvent.objects.create(idempotency_key=key[:160], event_type=event_type, payload=payload)
    except IntegrityError:
        return HttpResponse("duplicate", status=200)  # already received; acknowledge so the provider stops retrying

    outcome = "ignored"
    if event_type == "charge.success" and data.get("reference"):
        try:
            txn = finalize_payment(data["reference"])
            outcome = txn.status
            event.processed = True
        except PaymentError as exc:
            outcome = f"error: {exc}"[:120]
            event.delete()  # allow the provider's retry to be processed
            return HttpResponse("retry", status=500)
    elif event_type.startswith("charge.dispute") or event_type.startswith("refund."):
        log.warning("Provider %s event received for %s: review in the admin dashboard.", event_type, data.get("reference"))
        outcome = "flagged for review"
    event.outcome = outcome
    event.save(update_fields=["processed", "outcome"])
    return HttpResponse("ok")
