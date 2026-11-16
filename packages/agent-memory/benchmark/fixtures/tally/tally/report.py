"""Monthly reports."""
from datetime import date

from tally._vendor import moneyfmt


def month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year, month + 1, 1)
    return start, end


def monthly(entries: list[dict], year: int, month: int) -> dict[str, float]:
    start, end = month_range(year, month)
    totals: dict[str, float] = {}
    for e in entries:
        d = date.fromisoformat(e["date"])
        if start <= d < end:
            totals[e["category"]] = totals.get(e["category"], 0) + e["amount"]
    return totals


def render(totals: dict[str, float]) -> str:
    lines = [f"{cat:<16}{moneyfmt.format(amount):>12}" for cat, amount in sorted(totals.items())]
    lines.append(f"{'total':<16}{moneyfmt.format(sum(totals.values())):>12}")
    return "\n".join(lines)
