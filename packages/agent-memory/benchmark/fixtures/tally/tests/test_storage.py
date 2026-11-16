from tally import storage


def test_append_and_load_round_trip(tmp_path):
    path = tmp_path / "ledger.jsonl"
    storage.append({"amount": 1.0, "category": "food", "date": "2026-01-01"}, path)
    storage.append({"amount": 2.0, "category": "rent", "date": "2026-01-02"}, path)
    assert [e["category"] for e in storage.load(path)] == ["food", "rent"]


def test_missing_ledger_is_empty(tmp_path):
    assert storage.load(tmp_path / "nope.jsonl") == []
