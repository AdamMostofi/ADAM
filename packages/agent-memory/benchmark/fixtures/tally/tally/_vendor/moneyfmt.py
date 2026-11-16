"""moneyfmt 1.4 (vendored). Formats an amount for display."""
__version__ = "1.4"


def format(amount: float) -> str:
    return f"${amount:,.2f}"
