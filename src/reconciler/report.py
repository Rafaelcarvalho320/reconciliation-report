"""Turning a reconciliation into something a person or a pipeline can use.

Four renderers, because the answer is read by different audiences: a human
scanning a terminal, a spreadsheet, a dashboard, and a pull request comment.
All of them lead with the summary, because the first question is always "how
bad is it" and only then "which rows".
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from decimal import Decimal
from typing import Any

from reconciler.core import Reconciliation, iter_problems
from reconciler.schema import format_key

DEFAULT_LIMIT = 20


def _plain(value: Any) -> Any:
    """JSON and CSV cannot hold Decimal or date, and must not lose precision."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def as_json(result: Reconciliation, *, indent: int | None = 2) -> str:
    payload = {
        "summary": result.summary(),
        "clean": result.is_clean,
        "totals": {
            result.left_name: result.total_left,
            result.right_name: result.total_right,
        },
        "problems": [
            {"kind": kind, **{k: _plain(v) for k, v in row.items()}}
            for kind, row in iter_problems(result)
        ],
    }
    return json.dumps(payload, indent=indent, ensure_ascii=False)


def as_csv(result: Reconciliation) -> str:
    """One row per finding, with a stable column set.

    Findings carry different fields, so the header is the union of every key
    seen. Building it up front, rather than per section, is what keeps the file
    openable as a single sheet.
    """
    problems = [
        {"kind": kind, **{k: _plain(v) for k, v in row.items()}}
        for kind, row in iter_problems(result)
    ]
    if not problems:
        return "kind\n"

    columns: list[str] = []
    for row in problems:
        for column in row:
            if column not in columns:
                columns.append(column)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(problems)
    return buffer.getvalue()


def as_text(result: Reconciliation, *, limit: int = DEFAULT_LIMIT) -> str:
    lines: list[str] = []
    add = lines.append

    verdict = "CLEAN" if result.is_clean else f"{result.problem_count} PROBLEM(S)"
    add(f"Reconciliation: {result.left_name} vs {result.right_name}   [{verdict}]")
    add("=" * 72)
    add(f"  key      : {', '.join(result.schema.key_names)}")
    add(f"  compared : {', '.join(result.schema.compare_names) or '(keys only)'}")
    add("")
    add(f"  {result.left_name}: {result.total_left} record(s)")
    add(f"  {result.right_name}: {result.total_right} record(s)")
    add("")
    add(f"  matched      {result.matched}")
    add(f"  mismatched   {len(result.mismatched)}")
    add(f"  only in {result.left_name}   {len(result.only_left)}")
    add(f"  only in {result.right_name}   {len(result.only_right)}")
    if result.duplicate_left or result.duplicate_right:
        add(
            f"  duplicate keys   {len(result.duplicate_left)} / "
            f"{len(result.duplicate_right)}"
        )
    if result.unkeyed_left or result.unkeyed_right:
        add(
            f"  unkeyed rows     {len(result.unkeyed_left)} / "
            f"{len(result.unkeyed_right)}"
        )

    if result.is_clean:
        add("")
        add("The two sides agree.")
        return "\n".join(lines)

    def section(title: str, rows: list[str]) -> None:
        if not rows:
            return
        add("")
        add(f"{title} ({len(rows)})")
        add("-" * 72)
        for row in rows[:limit]:
            add(f"  {row}")
        if len(rows) > limit:
            add(f"  ... and {len(rows) - limit} more")

    section(
        "Mismatched",
        [
            f"{format_key(m.key)}\n"
            + "\n".join(
                f"      {d.field}: {result.left_name}={d.left!r}  "
                f"{result.right_name}={d.right!r}"
                for d in m.differences
            )
            for m in result.mismatched
        ],
    )
    section(
        f"Only in {result.left_name}",
        [format_key(result.schema.key_of(r) or ()) for r in result.only_left],
    )
    section(
        f"Only in {result.right_name}",
        [format_key(result.schema.key_of(r) or ()) for r in result.only_right],
    )
    section(
        "Duplicate keys",
        [
            f"{result.left_name}: {format_key(k)} x{c}"
            for k, c in result.duplicate_left.items()
        ]
        + [
            f"{result.right_name}: {format_key(k)} x{c}"
            for k, c in result.duplicate_right.items()
        ],
    )
    section(
        "Unkeyed rows",
        [f"{result.left_name}: {u.reason}" for u in result.unkeyed_left]
        + [f"{result.right_name}: {u.reason}" for u in result.unkeyed_right],
    )
    return "\n".join(lines)


def as_markdown(result: Reconciliation, *, limit: int = DEFAULT_LIMIT) -> str:
    """For pasting into a pull request or a ticket."""
    status = "✅ clean" if result.is_clean else f"❌ {result.problem_count} problem(s)"
    lines = [
        f"## Reconciliation: `{result.left_name}` vs `{result.right_name}`",
        "",
        f"**{status}** — key `{', '.join(result.schema.key_names)}`",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
    ]
    for label, value in result.summary().items():
        lines.append(f"| {label.replace('_', ' ')} | {value} |")

    if result.mismatched:
        lines += [
            "",
            "### Mismatched",
            "",
            f"| Key | Field | {result.left_name} | {result.right_name} |",
            "| --- | --- | --- | --- |",
        ]
        shown = 0
        for mismatch in result.mismatched:
            for difference in mismatch.differences:
                if shown >= limit:
                    break
                lines.append(
                    f"| `{format_key(mismatch.key)}` | {difference.field} "
                    f"| {difference.left} | {difference.right} |"
                )
                shown += 1
        if len(result.mismatched) > shown:
            lines.append(f"| ... | {len(result.mismatched) - shown} more | | |")

    return "\n".join(lines)


RENDERERS = {
    "text": as_text,
    "json": lambda r, **_: as_json(r),
    "csv": lambda r, **_: as_csv(r),
    "markdown": as_markdown,
}
