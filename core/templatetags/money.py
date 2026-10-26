from decimal import Decimal

from django import template

register = template.Library()

SYMBOLS = {"NGN": "₦", "USD": "$", "GBP": "£", "EUR": "€", "GHS": "GH₵", "KES": "KSh"}


@register.filter
def money(value, currency="NGN"):
    """Format a Decimal with one consistent style. Symbols live here, never in templates."""
    if value is None:
        return ""
    value = Decimal(value)
    symbol = SYMBOLS.get(currency, f"{currency} ")
    return f"{symbol}{value:,.2f}"


@register.filter
def price_or_free(book):
    if book.is_free:
        return "Free"
    return money(book.price, book.currency)
