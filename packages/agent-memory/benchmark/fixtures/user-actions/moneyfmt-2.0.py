"""moneyfmt 2.0 (vendored). Formats an amount for display.

2.0: ISO currency codes instead of symbols.
"""
__version__ = "2.0"


def format(amount: float, currency: str = "USD") -> str:
    return f"{currency} {amount:,.2f}"
