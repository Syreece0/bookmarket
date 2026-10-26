"""All money movement lives here. Every function is transactional and idempotent."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import User
from core.models import SiteSettings, audit
from core.money import ZERO, q, split_commission
from orders.models import Entitlement, Order, OrderItem

from .models import LedgerEntry, PayoutAccount, PayoutRequest, RefundRecord, new_adjustment_key

L = LedgerEntry
Kind = LedgerEntry.Kind


class FinanceError(Exception):
    pass


def _post(key, **fields):
    """Create a ledger entry once. A second call with the same key is a harmless no-op."""
    entry, _created = L.objects.get_or_create(key=key, defaults=fields)
    return entry


def fee_split(item_fee, policy):
    """Return (seller_share, platform_share) for one item's payment fee under the configured policy."""
    item_fee = q(item_fee)
    if policy == SiteSettings.FeeAllocation.SELLER:
        seller = item_fee
    elif policy == SiteSettings.FeeAllocation.SPLIT:
        seller = q(item_fee / 2)
    else:
        seller = ZERO
    return seller, item_fee - seller


def distribute_fee(total_fee, items):
    """Spread a payment fee across items in proportion to price; the last item absorbs rounding."""
    total_fee = q(total_fee)
    gross_total = sum((i.unit_price for i in items), ZERO)
    shares, assigned = [], ZERO
    for idx, item in enumerate(items):
        if idx == len(items) - 1:
            share = total_fee - assigned
        else:
            share = q(total_fee * item.unit_price / gross_total) if gross_total else ZERO
            assigned += share
        shares.append(share)
    return shares


@transaction.atomic
def allocate_order(order, provider_fee):
    """Split a verified, paid order into commission / seller share / fees and post ledger entries.

    Safe to call more than once: items already allocated are skipped and ledger keys are unique.
    Commission and fee-policy values are snapshotted onto each OrderItem."""
    site = SiteSettings.load()
    now = timezone.now()
    items = list(order.items.select_for_update().select_related("seller").order_by("id"))
    fee_shares = distribute_fee(provider_fee, items)
    available_at = (order.paid_at or now) + timedelta(days=site.payout_hold_days)

    for item, item_fee in zip(items, fee_shares):
        if item.allocated_at:
            continue
        gross = q(item.unit_price)
        rate = Decimal("0") if item.seller_is_admin else site.commission_rate
        commission, _seller_gross = split_commission(gross, rate) if gross > 0 else (ZERO, ZERO)
        seller_fee, platform_fee = fee_split(item_fee, site.fee_allocation)

        item.commission_rate = rate
        item.commission_amount = commission
        item.payment_fee = item_fee
        item.fee_borne_by_seller = seller_fee
        item.fee_borne_by_platform = platform_fee
        item.seller_net = gross - commission - seller_fee
        item.allocated_at = now
        item.save()

        base = f"item:{item.pk}"
        common = {"currency": item.currency, "order_item": item}
        _post(f"{base}:gross", account=L.Account.SELLER, kind=Kind.GROSS_SALE, seller=item.seller, amount=gross, **common)
        _post(f"{base}:earning", account=L.Account.SELLER, kind=Kind.EARNING, seller=item.seller,
              amount=gross - commission, available_at=available_at, **common)
        if seller_fee > 0:
            _post(f"{base}:feeshare", account=L.Account.SELLER, kind=Kind.FEE_SHARE, seller=item.seller,
                  amount=-seller_fee, available_at=available_at, **common)
        if commission > 0:
            _post(f"{base}:commission", account=L.Account.PLATFORM, kind=Kind.COMMISSION, amount=commission, **common)
        if platform_fee > 0:
            _post(f"{base}:platformfee", account=L.Account.PLATFORM, kind=Kind.PLATFORM_FEE, amount=-platform_fee, **common)


@transaction.atomic
def refund_item(item_id, actor, reason, kind=RefundRecord.Kind.REFUND, provider_reference=""):
    """Reverse a sale: revoke access and post reversing entries. The payment provider keeps its processing
    fee on refunds, so fee entries are deliberately left in place."""
    item = OrderItem.objects.select_for_update().select_related("order", "seller").get(pk=item_id)
    if item.order.status != Order.Status.PAID or not item.allocated_at:
        raise FinanceError("Only paid, allocated sales can be refunded.")
    if item.refunded_at:
        raise FinanceError("This sale has already been refunded.")
    now = timezone.now()
    item.refunded_at = now
    item.save(update_fields=["refunded_at"])
    RefundRecord.objects.create(order_item=item, kind=kind, amount=item.unit_price, reason=reason[:240],
                                provider_reference=provider_reference, created_by=actor)
    Entitlement.objects.filter(order_item=item, revoked_at__isnull=True).update(
        revoked_at=now, revoked_reason=f"{kind}: {reason}"[:120])

    base, common = f"item:{item.pk}", {"currency": item.currency, "order_item": item, "created_by": actor, "note": reason[:240]}
    seller_kind = Kind.CHARGEBACK if kind == RefundRecord.Kind.CHARGEBACK else Kind.REFUND
    _post(f"{base}:grossrefund", account=L.Account.SELLER, kind=Kind.GROSS_REFUND, seller=item.seller, amount=-item.unit_price, **common)
    _post(f"{base}:refund", account=L.Account.SELLER, kind=seller_kind, seller=item.seller,
          amount=-(item.unit_price - item.commission_amount), **common)
    if item.commission_amount > 0:
        _post(f"{base}:commissionreversal", account=L.Account.PLATFORM, kind=Kind.COMMISSION_REVERSAL,
              amount=-item.commission_amount, **common)

    order = item.order
    if not order.items.filter(refunded_at__isnull=True).exists():
        order.status = Order.Status.REFUNDED
        order.save(update_fields=["status"])
    audit(actor, f"order_item.{kind}", f"item {item.pk}", reason)
    return item


def seller_balances(user):
    """Return pending / available / withdrawable / paid-out totals for one seller."""
    now = timezone.now()
    qs = L.objects.filter(account=L.Account.SELLER, seller=user, kind__in=L.BALANCE_KINDS)
    total = qs.aggregate(s=Sum("amount"))["s"] or ZERO
    pending = qs.filter(available_at__gt=now).aggregate(s=Sum("amount"))["s"] or ZERO
    available = total - pending
    withdrawable = max(ZERO, min(available, total))
    paid_out = PayoutRequest.objects.filter(seller=user, status=PayoutRequest.Status.PAID).aggregate(s=Sum("amount"))["s"] or ZERO
    return {"total": total, "pending": pending, "available": available, "withdrawable": withdrawable, "paid_out": paid_out}


@transaction.atomic
def request_payout(user, amount):
    amount = q(amount)
    site = SiteSettings.load()
    User.objects.select_for_update().get(pk=user.pk)  # serialise concurrent requests per seller
    account = PayoutAccount.objects.filter(user=user).first()
    if not account:
        raise FinanceError("Add your bank details before requesting a payout.")
    if amount < site.minimum_payout:
        raise FinanceError(f"The minimum payout is {site.minimum_payout}.")
    if amount > seller_balances(user)["withdrawable"]:
        raise FinanceError("The amount is more than your available balance.")
    req = PayoutRequest.objects.create(
        seller=user, amount=amount, currency=site.default_currency,
        destination_snapshot=f"{account.bank_name} · {account.account_number} · {account.account_name}",
    )
    _post(f"payout:{req.pk}:reserve", account=L.Account.SELLER, kind=Kind.PAYOUT, seller=user, amount=-amount,
          currency=req.currency, note=f"Payout request #{req.pk}")
    return req


@transaction.atomic
def transition_payout(payout_id, new_status, actor, reference="", note=""):
    payout = PayoutRequest.objects.select_for_update().get(pk=payout_id)
    allowed = PayoutRequest.TRANSITIONS.get(payout.status, set())
    if new_status not in allowed:
        raise FinanceError(f"A {payout.status} payout cannot move to {new_status}.")
    if new_status == PayoutRequest.Status.PAID and not reference.strip():
        raise FinanceError("Enter the transfer reference before marking a payout as paid.")
    if new_status == PayoutRequest.Status.CANCELLED and actor.pk != payout.seller_id and not actor.is_platform_admin:
        raise FinanceError("Not allowed.")
    payout.status = new_status
    payout.handled_by = actor
    payout.note = note[:240] or payout.note
    if reference:
        payout.provider_reference = reference.strip()[:120]
    if new_status in (PayoutRequest.Status.PAID, *PayoutRequest.RELEASING):
        payout.processed_at = timezone.now()
    payout.save()
    if new_status in PayoutRequest.RELEASING:
        _post(f"payout:{payout.pk}:release", account=L.Account.SELLER, kind=Kind.PAYOUT_REVERSAL, seller=payout.seller,
              amount=payout.amount, currency=payout.currency, note=f"Payout #{payout.pk} {new_status}")
    audit(actor, f"payout.{new_status}", f"payout {payout.pk}", note)
    return payout


@transaction.atomic
def create_adjustment(seller, amount, reason, actor):
    amount = q(amount)
    if amount == 0 or not reason.strip():
        raise FinanceError("An adjustment needs a non-zero amount and a reason.")
    site = SiteSettings.load()
    entry = _post(new_adjustment_key(), account=L.Account.SELLER, kind=Kind.ADJUSTMENT, seller=seller, amount=amount,
                  currency=site.default_currency, note=reason[:240], created_by=actor)
    audit(actor, "finance.adjustment", f"seller {seller.pk}", f"{amount}: {reason}")
    return entry
