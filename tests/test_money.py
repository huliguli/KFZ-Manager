"""Cent arithmetic and German money parsing/formatting."""

import pytest

from modules.money import (
    MoneyParseError,
    euros_to_cents,
    format_eur,
    parse_eur,
    round_half_up,
    try_parse_eur,
)


def test_euros_to_cents_rounds_half_up():
    assert euros_to_cents("12.345") == 1235  # 12.345 € -> 1234.5 Cent -> 1235
    assert euros_to_cents(0.005) == 1
    assert euros_to_cents(10) == 1000


def test_round_half_up_vs_bankers():
    assert round_half_up(0.5) == 1
    assert round_half_up(1.5) == 2  # banker's rounding would give 2 as well
    assert round_half_up(2.5) == 3  # ...but here banker's would give 2


def test_format_eur_german():
    assert format_eur(123456) == "1.234,56 €"
    assert format_eur(-50000) == "-500,00 €"
    assert format_eur(75000, plus=True) == "+750,00 €"
    assert format_eur(0) == "0,00 €"


@pytest.mark.parametrize("text,cents", [
    ("1.234,56 €", 123456),
    ("1234,56", 123456),
    ("1234.56", 123456),
    ("1.234", 123400),
    ("1.234.567", 123456700),
    ("-58,80", -5880),
    ("1.500", 150000),
    ("0.500", 50),        # leading zero: decimal, not thousands
])
def test_parse_eur(text, cents):
    assert parse_eur(text) == cents


def test_parse_eur_rejects_garbage():
    with pytest.raises(MoneyParseError):
        parse_eur("abc")
    with pytest.raises(MoneyParseError):
        parse_eur("")
    assert try_parse_eur("abc") is None


def test_cent_sums_stay_integer():
    # The core discipline: aggregation never leaves integer space.
    amounts = [parse_eur("19,99"), parse_eur("0,01"), parse_eur("1.000,00")]
    assert sum(amounts) == 1999 + 1 + 100000
    assert isinstance(sum(amounts), int)
