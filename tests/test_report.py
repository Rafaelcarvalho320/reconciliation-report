"""Rendering a reconciliation."""

from __future__ import annotations

import csv
import io
import json

from reconciler import (
    IterableSource,
    Schema,
    as_csv,
    as_json,
    as_markdown,
    as_text,
    reconcile,
)

SCHEMA = Schema.build(key=["id"], compare=["total"], normalizers={"total": "money"})


def dirty():
    left = [
        {"id": "1", "total": "10.00"},
        {"id": "2", "total": "20.00"},
        {"id": "3", "total": "30.00"},
        {"id": "3", "total": "30.00"},
    ]
    right = [
        {"id": "1", "total": "10.00"},
        {"id": "2", "total": "99.00"},
        {"id": "4", "total": "40.00"},
    ]
    return reconcile(
        IterableSource(left, name="erp"), IterableSource(right, name="shop"), SCHEMA
    )


def clean():
    rows = [{"id": "1", "total": "10.00"}]
    return reconcile(
        IterableSource(rows, name="erp"),
        IterableSource(list(rows), name="shop"),
        SCHEMA,
    )


class TestText:
    def test_the_verdict_is_on_the_first_line(self) -> None:
        assert "CLEAN" in as_text(clean()).splitlines()[0]
        assert "PROBLEM" in as_text(dirty()).splitlines()[0]

    def test_a_clean_run_says_so_and_stops(self) -> None:
        assert "The two sides agree." in as_text(clean())

    def test_every_category_is_named(self) -> None:
        report = as_text(dirty())
        assert "Mismatched" in report
        assert "Only in erp" in report
        assert "Only in shop" in report
        assert "Duplicate keys" in report

    def test_both_values_are_shown_for_a_mismatch(self) -> None:
        report = as_text(dirty())
        assert "erp=Decimal('20.00')" in report
        assert "shop=Decimal('99.00')" in report

    def test_long_sections_are_truncated_with_a_count(self) -> None:
        left = [{"id": str(n), "total": "1"} for n in range(50)]
        result = reconcile(IterableSource(left), IterableSource([]), SCHEMA)
        report = as_text(result, limit=5)
        assert "... and 45 more" in report


class TestJson:
    def test_it_is_valid_json_with_a_summary(self) -> None:
        payload = json.loads(as_json(dirty()))
        assert payload["clean"] is False
        assert payload["summary"]["matched"] == 1
        assert payload["summary"]["mismatched"] == 1

    def test_decimals_survive_as_exact_strings(self) -> None:
        """Serialising money as a float would reintroduce the rounding error."""
        payload = json.loads(as_json(dirty()))
        mismatch = next(p for p in payload["problems"] if p["kind"] == "mismatch")
        assert mismatch["erp"] == "20.00"
        assert isinstance(mismatch["erp"], str)

    def test_a_clean_run_has_no_problems(self) -> None:
        payload = json.loads(as_json(clean()))
        assert payload["clean"] is True
        assert payload["problems"] == []


class TestCsv:
    def test_it_parses_back_as_a_single_sheet(self) -> None:
        rows = list(csv.DictReader(io.StringIO(as_csv(dirty()))))
        kinds = {row["kind"] for row in rows}
        assert kinds == {"only_in_erp", "only_in_shop", "mismatch", "duplicate_key"}

    def test_the_header_is_the_union_of_every_finding(self) -> None:
        """Findings carry different fields; one header keeps the file openable."""
        reader = csv.DictReader(io.StringIO(as_csv(dirty())))
        assert reader.fieldnames is not None
        assert "kind" in reader.fieldnames
        assert "field" in reader.fieldnames

    def test_a_clean_run_writes_only_a_header(self) -> None:
        assert as_csv(clean()).strip() == "kind"


class TestMarkdown:
    def test_it_leads_with_a_status(self) -> None:
        assert "clean" in as_markdown(clean())
        assert "problem" in as_markdown(dirty())

    def test_mismatches_become_a_table(self) -> None:
        report = as_markdown(dirty())
        assert "| Key | Field | erp | shop |" in report
        assert "| `2` | total | 20.00 | 99.00 |" in report
