"""Katalog-Matcher: condition logic against the vehicle profile."""

from datetime import date

from modules import catalog
from modules.models import CatalogItem, Vehicle

TODAY = date(2026, 7, 14)


def _item(conditions: dict | None = None, item_id: str = "seed-x") -> CatalogItem:
    return CatalogItem(id=item_id, name="Test", bedingungen=conditions or {})


def _diesel() -> Vehicle:
    return Vehicle(name="TDI", kraftstoff="diesel", partikelfilter="dpf",
                   fahrprofil="kurzstrecke", direkteinspritzung=True,
                   aufladung="turbo", getriebe="manuell", km_stand=120_000,
                   erstzulassung="2018-03-01")


def test_unconditional_item_matches_everything():
    assert catalog.matches(_item({}), Vehicle(name="leer"), today=TODAY)


def test_list_condition_or_semantics():
    item = _item({"kraftstoff": ["benzin", "diesel"]})
    assert catalog.matches(item, _diesel(), today=TODAY)
    assert not catalog.matches(
        item, Vehicle(name="EV", kraftstoff="elektro"), today=TODAY)


def test_conditions_are_anded():
    item = _item({"kraftstoff": ["diesel"], "fahrprofil": ["langstrecke"]})
    assert not catalog.matches(item, _diesel(), today=TODAY)  # fahrprofil differs


def test_missing_profile_value_fails_condition():
    # Unknown fuel type must NOT match a fuel-conditioned item (fail safe).
    item = _item({"kraftstoff": ["diesel"]})
    assert not catalog.matches(item, Vehicle(name="unbekannt"), today=TODAY)


def test_bool_condition_direkteinspritzung():
    item = _item({"direkteinspritzung": True})
    assert catalog.matches(item, _diesel(), today=TODAY)
    v = _diesel()
    v.direkteinspritzung = False
    assert not catalog.matches(item, v, today=TODAY)
    v.direkteinspritzung = None
    assert not catalog.matches(item, v, today=TODAY)


def test_min_laufleistung_uses_current_km():
    item = _item({"min_laufleistung_km": 100_000})
    assert catalog.matches(item, _diesel(), km_now=120_000, today=TODAY)
    assert not catalog.matches(item, _diesel(), km_now=80_000, today=TODAY)
    # Falls back to the profile reading when km_now is unknown.
    assert catalog.matches(item, _diesel(), today=TODAY)


def test_min_alter_jahre():
    item = _item({"min_alter_jahre": 4})
    assert catalog.matches(item, _diesel(), today=TODAY)  # EZ 2018 -> 8 Jahre
    young = _diesel()
    young.erstzulassung = "2025-01-01"
    assert not catalog.matches(item, young, today=TODAY)
    unknown = _diesel()
    unknown.erstzulassung = None
    assert not catalog.matches(item, unknown, today=TODAY)


def test_unknown_condition_key_fails_closed():
    # A future seed with a condition this app version does not know must not
    # mis-match — the whole item is suppressed.
    item = _item({"zukunftsfeld": "x"})
    assert not catalog.matches(item, _diesel(), today=TODAY)


def test_suggestions_exclude_hidden_and_adopted():
    items = [_item({}, "seed-a"), _item({}, "seed-b"), _item({}, "seed-c")]
    result = catalog.suggestions_for(
        items, _diesel(), hidden_ids={"seed-a"}, adopted_ids={"seed-b"}, today=TODAY)
    assert [i.id for i in result] == ["seed-c"]


def test_next_user_id_skips_existing():
    assert catalog.next_user_id(set()) == "user-1"
    assert catalog.next_user_id({"user-1", "user-2"}) == "user-3"
