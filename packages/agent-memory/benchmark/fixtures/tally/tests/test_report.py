from tally import report

ENTRIES = [
    {"amount": 12.5, "category": "food", "date": "2026-03-04"},
    {"amount": 3.0, "category": "transport", "date": "2026-03-20"},
    {"amount": 99.0, "category": "food", "date": "2026-04-01"},
]


def test_monthly_totals_by_category():
    assert report.monthly(ENTRIES, 2026, 3) == {"food": 12.5, "transport": 3.0}


def test_render_formats_money():
    out = report.render({"food": 12.5})
    assert "$12.50" in out
    assert out.splitlines()[-1].endswith("$12.50")
