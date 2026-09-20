"""Command line entry point.

Exit codes are the contract, because the most useful place to run a
reconciliation is a scheduled job that has to decide whether to page someone:

    0  the two sides agree
    1  differences were found
    2  the run itself failed (bad file, bad schema, unreadable column)

Collapsing 1 and 2 would mean a typo in a column name looks exactly like a
clean night, which is the worst possible failure for a monitoring job.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from collections.abc import Sequence
from pathlib import Path

from reconciler.core import reconcile
from reconciler.normalizers import BY_NAME
from reconciler.report import DEFAULT_LIMIT, RENDERERS
from reconciler.schema import Schema, SchemaError
from reconciler.sources import CsvSource, JsonSource, Source

EXIT_CLEAN = 0
EXIT_DIFFERENCES = 1
EXIT_ERROR = 2


def parse_pairs(values: Sequence[str], flag: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise SchemaError(f"{flag} expects field=value, got {item!r}")
        field, _, value = item.partition("=")
        pairs[field.strip()] = value.strip()
    return pairs


def open_source(path: str, delimiter: str, name: str | None) -> Source:
    suffix = Path(path).suffix.lower()
    if suffix in {".json", ".jsonl", ".ndjson"}:
        return JsonSource(path, name=name or "")
    return CsvSource(path, delimiter=delimiter, name=name or "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reconcile",
        description="Compare two datasets and report every way they disagree.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "normalizers: " + ", ".join(sorted(BY_NAME)) + "\n\n"
            "example:\n"
            "  reconcile erp.csv shop.csv --key order_id --compare total,status"
            " --normalize order_id=integer --normalize total=money"
            " --tolerance total=0.01 --format markdown"
        ),
    )
    parser.add_argument("left", help="Left dataset (CSV or JSON). Streamed.")
    parser.add_argument("right", help="Right dataset. Held in memory.")
    parser.add_argument(
        "--key",
        required=True,
        help="Comma-separated key field(s) the two sides are matched on.",
    )
    parser.add_argument(
        "--compare",
        default="",
        help="Comma-separated fields to compare. Omit to only check presence.",
    )
    parser.add_argument(
        "--normalize",
        action="append",
        default=[],
        metavar="FIELD=NORMALIZER",
        help="Per-field normalizer. Repeatable.",
    )
    parser.add_argument(
        "--tolerance",
        action="append",
        default=[],
        metavar="FIELD=AMOUNT",
        help="Numeric slack for a compared field, e.g. total=0.01. Repeatable.",
    )
    parser.add_argument(
        "--format",
        choices=sorted(RENDERERS),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Rows per section in text output (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument("--delimiter", default=",", help="CSV delimiter.")
    parser.add_argument("--left-name", help="Label for the left side in the report.")
    parser.add_argument("--right-name", help="Label for the right side.")
    parser.add_argument("--output", help="Write to this file instead of stdout.")
    parser.add_argument(
        "--fail-on-difference",
        dest="fail_on_difference",
        action="store_true",
        default=True,
        help="Exit 1 when differences are found (the default).",
    )
    parser.add_argument(
        "--no-fail-on-difference",
        dest="fail_on_difference",
        action="store_false",
        help="Always exit 0 unless the run itself failed.",
    )
    return parser


def split_fields(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def emit(rendered: str, output: str | None) -> None:
    """Write the report, surviving a console that cannot spell every character.

    A Windows console still defaults to a legacy code page, where the check
    mark in the markdown report raises UnicodeEncodeError and takes the whole
    run down with it. Asking for UTF-8 fixes it properly; degrading to ASCII is
    the fallback, because a slightly uglier report beats a traceback.
    """
    if output:
        Path(output).write_text(rendered + "\n", encoding="utf-8")
        return
    # Typed as TextIO, which has no reconfigure; at runtime it is a
    # TextIOWrapper, except when something has replaced it, which the suppress
    # below is there for.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8")
    try:
        print(rendered)
    except UnicodeEncodeError:
        print(rendered.encode("ascii", "replace").decode("ascii"))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        schema = Schema.build(
            key=split_fields(args.key),
            compare=split_fields(args.compare),
            normalizers=parse_pairs(args.normalize, "--normalize"),
            tolerances=parse_pairs(args.tolerance, "--tolerance"),
        )
        left = open_source(args.left, args.delimiter, args.left_name)
        right = open_source(args.right, args.delimiter, args.right_name)
        result = reconcile(
            left,
            right,
            schema,
            left_name=args.left_name,
            right_name=args.right_name,
        )
    except (SchemaError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"error: no such file: {exc.filename}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    renderer = RENDERERS[args.format]
    emit(renderer(result, limit=args.limit), args.output)

    if result.is_clean or not args.fail_on_difference:
        return EXIT_CLEAN
    return EXIT_DIFFERENCES


if __name__ == "__main__":
    raise SystemExit(main())
