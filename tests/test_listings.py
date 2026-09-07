import pytest

from etsykit.client import encode_form
from etsykit.errors import ValidationError
from etsykit.listings import bad_tag_chars, build_payload, validate_tags

BASE_ROW = {
    "title": "Handmade Ceramic Mug",
    "description": "A nice mug.",
    "price": "24.00",
    "quantity": "5",
    "who_made": "i_did",
    "when_made": "made_to_order",
    "taxonomy_id": "1633",
    "shipping_profile_id": "12345",
}


def test_minimal_create_row_builds():
    payload = build_payload(dict(BASE_ROW), is_update=False)
    assert payload["title"] == "Handmade Ceramic Mug"
    assert payload["price"] == 24.0
    assert payload["quantity"] == 5
    assert payload["type"] == "physical"


def test_missing_shipping_profile_warns_but_does_not_block_a_draft():
    # etsykit only creates drafts, and Etsy does not require a shipping profile on a
    # draft. Blocking here would stop a new seller from staging anything at all.
    row = dict(BASE_ROW)
    del row["shipping_profile_id"]
    warnings: list[str] = []
    payload = build_payload(row, is_update=False, warnings=warnings)
    assert payload["title"]
    assert any("shipping_profile_id" in w for w in warnings)


def test_digital_listing_does_not_warn_about_shipping():
    row = dict(BASE_ROW)
    del row["shipping_profile_id"]
    row["type"] = "download"
    warnings: list[str] = []
    assert build_payload(row, is_update=False, warnings=warnings)["type"] == "download"
    assert warnings == []


def test_title_over_limit_rejected():
    row = dict(BASE_ROW, title="x" * 141)
    with pytest.raises(ValidationError, match="141 chars"):
        build_payload(row, is_update=False)


def test_bad_enum_rejected():
    row = dict(BASE_ROW, who_made="me")
    with pytest.raises(ValidationError, match="who_made"):
        build_payload(row, is_update=False)


def test_decimal_comma_price_accepted():
    row = dict(BASE_ROW, price="19,90")
    assert build_payload(row, is_update=False)["price"] == pytest.approx(19.90)


def test_update_row_only_keeps_updatable_fields():
    # price and quantity are deliberately not patchable — they belong to inventory.
    payload = build_payload({"title": "New title", "price": "9.99"}, is_update=True)
    assert payload == {"title": "New title"}


def test_update_requires_at_least_one_field():
    with pytest.raises(ValidationError, match="no updatable fields"):
        build_payload({"listing_id": "1"}, is_update=True)


def test_state_only_on_update():
    row = dict(BASE_ROW, state="active")
    with pytest.raises(ValidationError, match="state can only be set"):
        build_payload(row, is_update=False)


def test_tags_are_split_and_kept():
    row = dict(BASE_ROW, tags="ceramic mug|coffee gift|stoneware")
    assert build_payload(row, is_update=False)["tags"] == ["ceramic mug", "coffee gift", "stoneware"]


def test_too_many_tags_rejected():
    row = dict(BASE_ROW, tags="|".join(f"tag{i}" for i in range(14)))
    with pytest.raises(ValidationError, match="Etsy allows 13"):
        build_payload(row, is_update=False)


def test_tag_over_20_chars_rejected():
    row = dict(BASE_ROW, tags="this tag is far too long to be accepted")
    with pytest.raises(ValidationError, match="max 20"):
        build_payload(row, is_update=False)


def test_unicode_tags_are_allowed():
    # Turkish, German and French letters must survive — str.isalnum is Unicode-aware.
    assert bad_tag_chars("çiçek düğün") == set()
    assert bad_tag_chars("café münze") == set()
    assert validate_tags(["çiçek", "düğün hediyesi"]) == []


def test_disallowed_tag_symbol_flagged():
    assert bad_tag_chars("mug!") == {"!"}
    assert validate_tags(["mug!"])


def test_duplicate_tags_flagged():
    assert any("duplicate" in p for p in validate_tags(["mug", "Mug"]))


def test_encode_form_joins_lists_with_commas():
    # Etsy documents tags as a comma-separated string; repeated keys silently lose data.
    encoded = encode_form({"tags": ["a", "b", "c"], "quantity": 3, "is_supply": False})
    assert encoded == {"tags": "a,b,c", "quantity": "3", "is_supply": "false"}


def test_encode_form_drops_none_and_empty_lists():
    assert encode_form({"a": None, "b": [], "c": 1}) == {"c": "1"}
