"""Normalizers: the part that decides what counts as "the same value"."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from reconciler.normalizers import (
    as_date,
    boolean,
    digits,
    integer,
    lower,
    money,
    resolve,
    text,
    unaccented,
)


@pytest.mark.parametrize("raw", ["", "  ", "-", "N/A", "null", "NULL", "none", "nan"])
def test_every_spelling_of_empty_becomes_none(raw: str) -> None:
    assert text(raw) is None


def test_whitespace_is_collapsed_not_just_trimmed() -> None:
    assert text("  Rua   das   Flores  ") == "Rua das Flores"


def test_lower_folds_case() -> None:
    assert lower("PENDENTE") == lower("Pendente") == "pendente"


def test_unaccented_matches_an_export_that_lost_its_accents() -> None:
    assert unaccented("São Paulo") == unaccented("Sao Paulo")


class TestIdentifiers:
    def test_leading_zeros_do_not_make_two_different_orders(self) -> None:
        assert integer("00042") == integer("42") == integer(42) == 42

    def test_non_numeric_ids_are_none_rather_than_a_crash(self) -> None:
        assert integer("ORD-42") is None

    def test_punctuation_in_documents_is_ignored(self) -> None:
        assert digits("123.456.789-00") == digits("12345678900") == "12345678900"

    def test_a_document_with_no_digits_is_empty(self) -> None:
        assert digits("---") is None


class TestMoney:
    def test_it_returns_decimal_never_float(self) -> None:
        assert isinstance(money("10.50"), Decimal)

    def test_trailing_zeros_do_not_change_the_amount(self) -> None:
        assert money("1234.50") == money("1234.5")

    def test_brazilian_formatting(self) -> None:
        assert money("1.234,56") == Decimal("1234.56")

    def test_american_formatting(self) -> None:
        assert money("1,234.56") == Decimal("1234.56")

    def test_currency_symbols_are_stripped(self) -> None:
        assert money("R$ 1.234,56") == Decimal("1234.56")

    def test_comma_only_is_a_decimal_separator(self) -> None:
        assert money("10,50") == Decimal("10.50")

    def test_it_avoids_the_float_rounding_that_invents_differences(self) -> None:
        """0.1 + 0.2 != 0.3 in binary float, and that becomes a fake mismatch."""
        total = money("0.1") + money("0.2")
        assert total == money("0.3")
        assert 0.1 + 0.2 != 0.3

    def test_garbage_is_none(self) -> None:
        assert money("about ten") is None


class TestDates:
    @pytest.mark.parametrize(
        "raw", ["2026-03-04", "04/03/2026", "2026/03/04", "04-03-2026"]
    )
    def test_common_formats_land_on_the_same_day(self, raw: str) -> None:
        assert as_date(raw) == date(2026, 3, 4)

    def test_a_timestamp_is_reduced_to_its_date(self) -> None:
        """Comparing a date to a timestamp otherwise fails every hour but one."""
        assert as_date("2026-03-04T23:59:00") == as_date("2026-03-04")
        assert as_date(datetime(2026, 3, 4, 23, 59)) == date(2026, 3, 4)

    def test_unparseable_dates_are_none(self) -> None:
        assert as_date("last tuesday") is None


@pytest.mark.parametrize("raw", ["1", "true", "T", "yes", "sim", "S"])
def test_truthy_spellings(raw: str) -> None:
    assert boolean(raw) is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "nao", "não"])
def test_falsy_spellings(raw: str) -> None:
    assert boolean(raw) is False


def test_normalizers_resolve_by_name() -> None:
    assert resolve("money") is money


def test_an_unknown_normalizer_names_the_valid_ones() -> None:
    with pytest.raises(ValueError, match="known:"):
        resolve("magic")
