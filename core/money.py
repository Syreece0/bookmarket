"""Decimal-only money helpers. Never use float for money."""
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def q(value) -> Decimal:
    """Quantize to 2 decimal places using one consistent rounding rule (half-up)."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_minor_units(value) -> int:
    """Convert a major-unit Decimal (e.g. naira) to provider minor units (e.g. kobo)."""
    return int((q(value) * 100).to_integral_value())


def from_minor_units(value) -> Decimal:
    return q(Decimal(int(value)) / Decimal(100))


def split_commission(gross, rate):
    """Return (commission, seller_share) so that commission + seller_share == gross exactly."""
    gross = q(gross)
    commission = q(gross * Decimal(rate))
    return commission, gross - commission
