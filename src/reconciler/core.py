"""The reconciliation itself.

Strategy is a hash join: the right side is indexed in memory, the left side is
streamed past it. That makes peak memory a function of the *right* side alone,
so the rule when one export dwarfs the other is to put the big one on the left.

A sort-merge join would hold neither side in memory, but it needs both inputs
sorted by the same normalized key, which an arbitrary CSV export is not. This
keeps the honest constraint visible instead of pretending it is not there.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from reconciler.schema import Key, Schema
from reconciler.sources import Record, Source


@dataclass(frozen=True)
class Difference:
    """One field that disagrees between two records with the same key."""

    field: str
    left: Any
    right: Any


@dataclass(frozen=True)
class Mismatch:
    """A key present on both sides whose compared fields disagree."""

    key: Key
    differences: tuple[Difference, ...]
    left: Record
    right: Record


@dataclass(frozen=True)
class Unkeyed:
    """A record that could not be keyed at all: a broken row, not a difference."""

    record: Record
    reason: str


@dataclass
class Reconciliation:
    """Everything the comparison found."""

    schema: Schema
    left_name: str = "left"
    right_name: str = "right"

    matched: int = 0
    only_left: list[Record] = field(default_factory=list)
    only_right: list[Record] = field(default_factory=list)
    mismatched: list[Mismatch] = field(default_factory=list)
    duplicate_left: dict[Key, int] = field(default_factory=dict)
    duplicate_right: dict[Key, int] = field(default_factory=dict)
    unkeyed_left: list[Unkeyed] = field(default_factory=list)
    unkeyed_right: list[Unkeyed] = field(default_factory=list)

    @staticmethod
    def _extra_copies(duplicates: dict[Key, int]) -> int:
        """Rows beyond the first for each duplicated key.

        The first occurrence of a duplicated key is already counted as matched,
        mismatched or missing, so only the surplus copies are still unaccounted
        for. Adding the full count instead would make the totals exceed the
        number of rows that actually went in.
        """
        return sum(duplicates.values()) - len(duplicates)

    @property
    def total_left(self) -> int:
        """Every record read from the left side, however it was classified."""
        return (
            self.matched
            + len(self.mismatched)
            + len(self.only_left)
            + self._extra_copies(self.duplicate_left)
            + len(self.unkeyed_left)
        )

    @property
    def total_right(self) -> int:
        return (
            self.matched
            + len(self.mismatched)
            + len(self.only_right)
            + self._extra_copies(self.duplicate_right)
            + len(self.unkeyed_right)
        )

    @property
    def problem_count(self) -> int:
        return (
            len(self.only_left)
            + len(self.only_right)
            + len(self.mismatched)
            + len(self.duplicate_left)
            + len(self.duplicate_right)
            + len(self.unkeyed_left)
            + len(self.unkeyed_right)
        )

    @property
    def is_clean(self) -> bool:
        """True when the two sides agree completely.

        Duplicates and unkeyed rows count as problems. A reconciliation that
        called itself clean while one side had the same key twice would be
        reporting on a comparison it did not actually make.
        """
        return self.problem_count == 0

    def summary(self) -> dict[str, int]:
        return {
            "matched": self.matched,
            "mismatched": len(self.mismatched),
            f"only_in_{self.left_name}": len(self.only_left),
            f"only_in_{self.right_name}": len(self.only_right),
            f"duplicate_keys_in_{self.left_name}": len(self.duplicate_left),
            f"duplicate_keys_in_{self.right_name}": len(self.duplicate_right),
            f"unkeyed_in_{self.left_name}": len(self.unkeyed_left),
            f"unkeyed_in_{self.right_name}": len(self.unkeyed_right),
        }


def _index(
    records: Iterable[Record], schema: Schema
) -> tuple[dict[Key, Record], dict[Key, int], list[Unkeyed]]:
    """Load one side into memory, keyed, counting duplicates as it goes.

    The first record wins a duplicated key, so the comparison still has
    something to work with, and the key is reported as duplicated so nobody
    mistakes that choice for a verdict.
    """
    indexed: dict[Key, Record] = {}
    counts: Counter[Key] = Counter()
    unkeyed: list[Unkeyed] = []

    for record in records:
        key = schema.key_of(record)
        if key is None:
            unkeyed.append(
                Unkeyed(record, f"missing key field(s): {', '.join(schema.key_names)}")
            )
            continue
        counts[key] += 1
        if key not in indexed:
            indexed[key] = record

    duplicates = {key: count for key, count in counts.items() if count > 1}
    return indexed, duplicates, unkeyed


def _differences(left: Record, right: Record, schema: Schema) -> tuple[Difference, ...]:
    found = []
    for spec in schema.compare:
        left_value = spec.read(left)
        right_value = spec.read(right)
        if not spec.equal(left_value, right_value):
            found.append(Difference(spec.name, left_value, right_value))
    return tuple(found)


def reconcile(
    left: Source | Iterable[Record],
    right: Source | Iterable[Record],
    schema: Schema,
    *,
    left_name: str | None = None,
    right_name: str | None = None,
) -> Reconciliation:
    """Compare two sides and report every way they disagree.

    The right side is indexed in memory; the left side is streamed.
    """
    result = Reconciliation(
        schema=schema,
        left_name=left_name or str(getattr(left, "name", "left")),
        right_name=right_name or str(getattr(right, "name", "right")),
    )

    indexed, result.duplicate_right, result.unkeyed_right = _index(right, schema)
    unmatched_right = set(indexed)
    seen_left: Counter[Key] = Counter()

    for record in left:
        key = schema.key_of(record)
        if key is None:
            result.unkeyed_left.append(
                Unkeyed(record, f"missing key field(s): {', '.join(schema.key_names)}")
            )
            continue

        seen_left[key] += 1
        if seen_left[key] > 1:
            # Already compared on its first appearance; counted, not re-reported.
            continue

        counterpart = indexed.get(key)
        if counterpart is None:
            result.only_left.append(record)
            continue

        unmatched_right.discard(key)
        differences = _differences(record, counterpart, schema)
        if differences:
            result.mismatched.append(
                Mismatch(
                    key=key, differences=differences, left=record, right=counterpart
                )
            )
        else:
            result.matched += 1

    result.duplicate_left = {
        key: count for key, count in seen_left.items() if count > 1
    }
    result.only_right = [indexed[key] for key in indexed if key in unmatched_right]
    return result


def iter_problems(result: Reconciliation) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Flatten every finding into ``(kind, row)`` pairs, for CSV or JSON output."""
    from reconciler.schema import format_key

    for record in result.only_left:
        yield f"only_in_{result.left_name}", dict(record)
    for record in result.only_right:
        yield f"only_in_{result.right_name}", dict(record)
    for mismatch in result.mismatched:
        for difference in mismatch.differences:
            yield (
                "mismatch",
                {
                    "key": format_key(mismatch.key),
                    "field": difference.field,
                    result.left_name: difference.left,
                    result.right_name: difference.right,
                },
            )
    for side, duplicates in (
        (result.left_name, result.duplicate_left),
        (result.right_name, result.duplicate_right),
    ):
        for key, count in duplicates.items():
            yield (
                "duplicate_key",
                {
                    "side": side,
                    "key": format_key(key),
                    "occurrences": count,
                },
            )
    for side, unkeyed in (
        (result.left_name, result.unkeyed_left),
        (result.right_name, result.unkeyed_right),
    ):
        for item in unkeyed:
            yield "unkeyed", {"side": side, "reason": item.reason, **dict(item.record)}
