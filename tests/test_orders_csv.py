import time

import pytest

from etsykit.csvio import read_rows, split_multi, write_rows
from etsykit.errors import ValidationError
from etsykit.orders import flatten_receipt, money, parse_since


def test_parse_since_relative():
    now = time.time()
    assert now - parse_since("30d") == pytest.approx(30 * 86400, abs=120)
    assert now - parse_since("2w") == pytest.approx(14 * 86400, abs=120)


def test_parse_since_iso_date():
    assert parse_since("2026-01-01") == 1767225600


def test_parse_since_rejects_nonsense():
    with pytest.raises(ValidationError, match="Could not read"):
        parse_since("last tuesday")


def test_money_uses_the_divisor():
    assert money({"amount": 2450, "divisor": 100, "currency_code": "USD"}) == ("24.50", "USD")


def test_money_handles_missing_values():
    assert money(None) == ("", "")


def test_flatten_receipt_collapses_line_items():
    row = flatten_receipt(
        {
            "receipt_id": 42,
            "created_timestamp": 1767225600,
            "name": "Ada Lovelace",
            "city": "London",
            "country_iso": "GB",
            "grandtotal": {"amount": 4900, "divisor": 100, "currency_code": "GBP"},
            "transactions": [
                {"title": "Ceramic Mug", "quantity": 2, "sku": "MUG-01"},
                {"title": "Saucer", "quantity": 1},
            ],
            "shipments": [{"tracking_code": "AB123"}],
        }
    )
    assert row["receipt_id"] == 42
    assert row["items"] == ["Ceramic Mug x2", "Saucer x1"]
    assert row["skus"] == ["MUG-01"]
    assert row["item_count"] == 3
    assert row["order_total"] == "49.00"
    assert row["tracking_codes"] == ["AB123"]


def test_split_multi_accepts_pipes_and_commas():
    assert split_multi("a|b|c") == ["a", "b", "c"]
    assert split_multi("a, b") == ["a", "b"]
    assert split_multi("") == []


def test_csv_round_trip_preserves_unicode_and_lists(tmp_path):
    path = tmp_path / "out.csv"
    write_rows(path, [{"title": "Çiçek düğün", "tags": ["a", "b"]}], columns=["title", "tags"])
    rows = read_rows(path)
    assert rows[0]["title"] == "Çiçek düğün"
    assert split_multi(rows[0]["tags"]) == ["a", "b"]


def test_read_rows_skips_blank_trailing_rows(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text("title,price\nMug,10\n,\n", encoding="utf-8-sig")
    assert len(read_rows(path)) == 1
