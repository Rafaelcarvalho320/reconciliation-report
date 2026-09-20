"""Value normalizers.

This is where reconciliation actually lives or dies. Two systems almost never
disagree about the data; they disagree about how it is written down. The order
id is ``00042`` on one side and ``42`` on the other, the total is ``1234.50``
here and ``1234.5`` there, the document number carries punctuation in one place
and not the other, and "no value" is spelled ``""``, ``NULL``, ``N/A`` and
``-`` depending on who exported it.

Comparing raw strings reports all of that as a difference and buries the three
rows that genuinely differ. Normalizing first is what makes the output readable.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

Normalizer = Callable[[Any], Any]

#: Spellings of "empty" that exports produce. All of them become None.
NULL_TOKENS = frozenset({"", "-", "--", "n/a", "na", "null", "none", "nil", "nan"})

_NON_DIGITS = re.compile(r"\D+")
_WHITESPACE = re.compile(r"\s+")


def identity(value: Any) -> Any:
    return value


def as_none_if_blank(value: Any) -> Any:
    """Collapse every spelling of "no value" into ``None``."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in NULL_TOKENS:
        return None
    return value


def text(value: Any) -> str | None:
    """Trimmed text with runs of whitespace collapsed to one space."""
    value = as_none_if_blank(value)
    if value is None:
        return None
    return _WHITESPACE.sub(" ", str(value).strip())


def lower(value: Any) -> str | None:
    """Case-insensitive text. Uses casefold, so it also folds non-ASCII."""
    cleaned = text(value)
    return None if cleaned is None else cleaned.casefold()


def unaccented(value: Any) -> str | None:
    """Case-insensitive and accent-insensitive.

    ``"Sao Paulo"`` and ``"São Paulo"`` are the same city; one export just lost
    the accents on the way through a legacy encoding.
    """
    cleaned = lower(value)
    if cleaned is None:
        return None
    decomposed = unicodedata.normalize("NFKD", cleaned)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def digits(value: Any) -> str | None:
    """Only the digits, for documents, phone numbers and zip codes.

    ``"123.456.789-00"`` and ``"12345678900"`` are the same document written by
    two systems with different opinions about punctuation.
    """
    cleaned = text(value)
    if cleaned is None:
        return None
    stripped = _NON_DIGITS.sub("", cleaned)
    return stripped or None


def integer(value: Any) -> int | None:
    """Numeric identity, so ``"00042"``, ``"42"`` and ``42`` all agree."""
    cleaned = text(value)
    if cleaned is None:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def money(value: Any) -> Decimal | None:
    """Decimal, never float.

    ``0.1 + 0.2 != 0.3`` in binary floating point, which in a reconciliation
    means inventing differences of a hundredth of a cent and reporting them as
    real. Accepts both ``1.234,56`` and ``1,234.56``.
    """
    cleaned = text(value)
    if cleaned is None:
        return None
    if isinstance(value, Decimal):
        return value
    cleaned = cleaned.replace(" ", "").replace("R$", "").replace("$", "")
    if "," in cleaned and "." in cleaned:
        # Whichever separator comes last is the decimal one.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def as_date(value: Any) -> date | None:
    """A calendar date, ignoring any time component.

    Reconciling a date against a timestamp is a comparison that fails all day
    and passes at midnight, which is the sort of bug that takes a week to spot.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    cleaned = text(value)
    if cleaned is None:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(cleaned[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        return None


def boolean(value: Any) -> bool | None:
    """The many ways a CSV spells true and false."""
    cleaned = lower(value)
    if cleaned is None:
        return None
    if cleaned in {"1", "true", "t", "yes", "y", "sim", "s"}:
        return True
    if cleaned in {"0", "false", "f", "no", "n", "nao", "não"}:
        return False
    return None


#: Resolvable by name, which is what lets the CLI take --normalize total=money.
BY_NAME: dict[str, Normalizer] = {
    "identity": identity,
    "text": text,
    "lower": lower,
    "unaccented": unaccented,
    "digits": digits,
    "integer": integer,
    "money": money,
    "date": as_date,
    "boolean": boolean,
}


def resolve(name: str) -> Normalizer:
    try:
        return BY_NAME[name]
    except KeyError:
        known = ", ".join(sorted(BY_NAME))
        raise ValueError(f"unknown normalizer {name!r}; known: {known}") from None
