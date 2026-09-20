"""What to match on, what to compare, and how tolerant to be."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from reconciler.normalizers import Normalizer, identity, resolve

#: The key returned for a record: normalized values of every key field.
Key = tuple[Any, ...]


class SchemaError(Exception):
    """The schema itself is wrong, as opposed to the data being wrong."""


@dataclass(frozen=True)
class Field:
    """One column, and the rules for reading it.

    ``tolerance`` only applies to values that normalize to numbers. It exists
    because two systems that round at different points legitimately disagree by
    a cent, and a reconciliation that reports ten thousand one-cent differences
    is a reconciliation nobody reads.
    """

    name: str
    normalizer: Normalizer = identity
    tolerance: Decimal | None = None

    def read(self, record: Mapping[str, Any]) -> Any:
        return self.normalizer(record.get(self.name))

    def equal(self, left: Any, right: Any) -> bool:
        if self.tolerance is not None:
            if left is None or right is None:
                return left is right
            if isinstance(left, Decimal) and isinstance(right, Decimal):
                return abs(left - right) <= self.tolerance
            try:
                return abs(Decimal(str(left)) - Decimal(str(right))) <= self.tolerance
            except (ArithmeticError, ValueError):
                return bool(left == right)
        return bool(left == right)


@dataclass(frozen=True)
class Schema:
    """The key fields and the fields to compare.

    An empty ``compare`` is allowed and means "only tell me which records are
    missing from each side", which is a perfectly common question.
    """

    key: tuple[Field, ...]
    compare: tuple[Field, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.key:
            raise SchemaError("a schema needs at least one key field")
        overlap = {f.name for f in self.key} & {f.name for f in self.compare}
        if overlap:
            # Comparing a key field can never produce a difference, since rows
            # only ever meet when their keys already match. Silently accepting
            # it would promise a check that does nothing.
            raise SchemaError(
                f"key fields cannot also be compared: {', '.join(sorted(overlap))}"
            )

    @property
    def key_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.key)

    @property
    def compare_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.compare)

    def key_of(self, record: Mapping[str, Any]) -> Key | None:
        """The record's key, or ``None`` when any key part is missing.

        A record that cannot be keyed is not a difference, it is a broken row,
        and the report counts it separately so it never hides inside the
        "missing from the other side" bucket.
        """
        values = tuple(f.read(record) for f in self.key)
        if any(value is None or value == "" for value in values):
            return None
        return values

    @classmethod
    def build(
        cls,
        key: Sequence[str],
        compare: Sequence[str] = (),
        normalizers: Mapping[str, str] | None = None,
        tolerances: Mapping[str, str | Decimal] | None = None,
        default_key_normalizer: str = "text",
        default_compare_normalizer: str = "text",
    ) -> Schema:
        """Build a schema from plain names, the way the CLI passes them."""
        normalizers = normalizers or {}
        tolerances = tolerances or {}

        known = set(key) | set(compare)
        unknown = (set(normalizers) | set(tolerances)) - known
        if unknown:
            raise SchemaError(
                "normalizer or tolerance given for a field that is neither a key "
                f"nor compared: {', '.join(sorted(unknown))}"
            )

        def make(name: str, default: str, allow_tolerance: bool) -> Field:
            normalizer = (
                resolve(normalizers[name]) if name in normalizers else resolve(default)
            )
            tolerance: Decimal | None = None
            if allow_tolerance and name in tolerances:
                raw = tolerances[name]
                tolerance = raw if isinstance(raw, Decimal) else Decimal(str(raw))
                if tolerance < 0:
                    raise SchemaError(f"tolerance for {name!r} cannot be negative")
            return Field(name=name, normalizer=normalizer, tolerance=tolerance)

        return cls(
            key=tuple(make(n, default_key_normalizer, False) for n in key),
            compare=tuple(make(n, default_compare_normalizer, True) for n in compare),
        )


def format_key(key: Key) -> str:
    return " | ".join("" if part is None else str(part) for part in key)


__all__ = ["Field", "Key", "Schema", "SchemaError", "format_key"]
