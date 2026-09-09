"""Output you can screenshot without exposing your shop.

CLI output gets shared far more often than anyone plans for, and a listing title is
enough to find the shop it belongs to on Etsy. `--anonymise` keeps the findings
readable and drops the identity.
"""

import pytest

from etsykit import cli


@pytest.fixture
def anonymised(monkeypatch):
    monkeypatch.setattr(cli, "ANONYMISE", True)


@pytest.fixture
def plain(monkeypatch):
    monkeypatch.setattr(cli, "ANONYMISE", False)


def test_nothing_is_hidden_by_default(plain):
    assert cli._hide("ExampleShopName", "shop") == "ExampleShopName"
    assert cli._hide(11111111, "id") == "11111111"
    assert cli._hide("Dining Room Wallpaper | Lavender") == "Dining Room Wallpaper | Lavender"


def test_a_shop_name_is_replaced(anonymised):
    hidden = cli._hide("ExampleShopName", "shop")
    assert "ExampleShopName" not in hidden
    assert hidden == "‹your shop›"


def test_placeholders_avoid_rich_markup_syntax(anonymised):
    # "[hidden]" is markup to Rich, which prints nothing at all — a redaction that
    # looks like a missing value instead of a hidden one.
    for kind in ("id", "title", "shop", "url", "unknown"):
        placeholder = cli._hide("secret", kind)
        assert placeholder.strip(), "a redaction must still be visible"
        assert "[" not in placeholder and "]" not in placeholder


def test_ids_are_replaced(anonymised):
    for value in (11111111, "2222222222", 3333333333):
        assert str(value) not in cli._hide(value, "id")


def test_titles_are_replaced(anonymised):
    # A title is searchable on Etsy, so it identifies the shop as surely as its name.
    title = "Soy Wax Candle Gift Set | Hand Poured Lavender Scented"
    assert cli._hide(title) == "‹hidden›"
    assert "Lavender" not in cli._hide(title)


def test_urls_are_replaced(anonymised):
    assert "etsy.com" not in cli._hide("https://www.etsy.com/shop/Example", "url")


def test_an_unknown_kind_still_hides(anonymised):
    # Fail closed: a caller passing a category we did not anticipate must not leak.
    assert cli._hide("something identifying", "not-a-known-kind") == "‹hidden›"


def test_the_environment_variable_is_read_at_import(monkeypatch):
    import importlib

    monkeypatch.setenv("ETSYKIT_ANONYMISE", "1")
    reloaded = importlib.reload(cli)
    try:
        assert reloaded.ANONYMISE is True
    finally:
        monkeypatch.delenv("ETSYKIT_ANONYMISE", raising=False)
        importlib.reload(cli)


@pytest.mark.parametrize("value", ["", "0", "no", "off", "false"])
def test_other_environment_values_leave_it_off(monkeypatch, value):
    import importlib

    monkeypatch.setenv("ETSYKIT_ANONYMISE", value)
    reloaded = importlib.reload(cli)
    try:
        assert reloaded.ANONYMISE is False
    finally:
        monkeypatch.delenv("ETSYKIT_ANONYMISE", raising=False)
        importlib.reload(cli)


def test_no_test_fixture_carries_a_real_shop_niche():
    """Test data must not fingerprint whoever was running the tool when a bug was found.

    A public test file is a fingerprint: anyone reading it learns what the author sells.
    """
    from pathlib import Path

    here = Path(__file__).resolve()
    banned = ("candle", "exampleshopname", "peel and stick wallpaper")
    for path in here.parent.glob("test_*.py"):
        if path.resolve() == here:
            continue  # this file necessarily contains the words it bans
        text = path.read_text(encoding="utf-8").lower()
        for term in banned:
            assert term not in text, f"{path.name} carries a real shop's vocabulary: {term}"
