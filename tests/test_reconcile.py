"""The comparison itself."""

from __future__ import annotations

from decimal import Decimal

import pytest

from reconciler import IterableSource, Schema, SchemaError, reconcile


def build(**kwargs: object) -> Schema:
    options: dict[str, object] = {"key": ["id"], "compare": ["total", "status"]}
    options.update(kwargs)
    return Schema.build(**options)  # type: ignore[arg-type]


def run(left: list[dict], right: list[dict], schema: Schema | None = None):
    return reconcile(
        IterableSource(left, name="erp"),
        IterableSource(right, name="shop"),
        schema or build(),
    )


class TestAgreement:
    def test_identical_sides_are_clean(self) -> None:
        rows = [{"id": "1", "total": "10.00", "status": "paid"}]
        result = run(rows, list(rows))
        assert result.is_clean
        assert result.matched == 1
        assert result.problem_count == 0

    def test_the_side_names_come_from_the_sources(self) -> None:
        result = run([], [])
        assert result.left_name == "erp"
        assert result.right_name == "shop"

    def test_column_order_does_not_matter(self) -> None:
        left = [{"id": "1", "total": "10.00", "status": "paid"}]
        right = [{"status": "paid", "id": "1", "total": "10.00"}]
        assert run(left, right).is_clean

    def test_extra_columns_are_ignored(self) -> None:
        """Only the declared fields are compared; exports carry noise."""
        left = [{"id": "1", "total": "10.00", "status": "paid", "internal": "x"}]
        right = [{"id": "1", "total": "10.00", "status": "paid", "note": "y"}]
        assert run(left, right).is_clean


class TestMissingRecords:
    def test_a_record_only_on_the_left(self) -> None:
        result = run([{"id": "1"}, {"id": "2"}], [{"id": "1"}])
        assert [r["id"] for r in result.only_left] == ["2"]
        assert result.only_right == []

    def test_a_record_only_on_the_right(self) -> None:
        result = run([{"id": "1"}], [{"id": "1"}, {"id": "9"}])
        assert [r["id"] for r in result.only_right] == ["9"]

    def test_both_directions_at_once(self) -> None:
        result = run([{"id": "1"}, {"id": "2"}], [{"id": "2"}, {"id": "3"}])
        assert [r["id"] for r in result.only_left] == ["1"]
        assert [r["id"] for r in result.only_right] == ["3"]
        assert result.matched == 1

    def test_empty_sides_are_clean(self) -> None:
        assert run([], []).is_clean

    def test_everything_missing_from_an_empty_side(self) -> None:
        result = run([{"id": "1"}, {"id": "2"}], [])
        assert len(result.only_left) == 2


class TestMismatches:
    def test_a_differing_field_is_reported_with_both_values(self) -> None:
        result = run(
            [{"id": "1", "total": "10.00", "status": "paid"}],
            [{"id": "1", "total": "10.00", "status": "pending"}],
        )
        assert result.matched == 0
        (mismatch,) = result.mismatched
        (difference,) = mismatch.differences
        assert difference.field == "status"
        assert (difference.left, difference.right) == ("paid", "pending")

    def test_several_fields_differing_are_all_reported(self) -> None:
        result = run(
            [{"id": "1", "total": "10.00", "status": "paid"}],
            [{"id": "1", "total": "99.00", "status": "pending"}],
        )
        assert {d.field for d in result.mismatched[0].differences} == {
            "total",
            "status",
        }

    def test_both_original_records_are_kept_for_context(self) -> None:
        left = {"id": "1", "total": "10.00", "status": "paid", "note": "keep me"}
        right = {"id": "1", "total": "10.00", "status": "pending"}
        (mismatch,) = run([left], [right]).mismatched
        assert mismatch.left["note"] == "keep me"
        assert mismatch.right == right


class TestNormalizationDuringComparison:
    def test_leading_zeros_in_the_key_still_match(self) -> None:
        schema = build(key=["id"], compare=[], normalizers={"id": "integer"})
        result = run([{"id": "00042"}], [{"id": "42"}], schema)
        assert result.matched == 1

    def test_money_written_differently_is_the_same_amount(self) -> None:
        schema = build(compare=["total"], normalizers={"total": "money"})
        result = run(
            [{"id": "1", "total": "1.234,50"}],
            [{"id": "1", "total": "1234.5"}],
            schema,
        )
        assert result.is_clean

    def test_case_differences_can_be_told_to_not_count(self) -> None:
        schema = build(compare=["status"], normalizers={"status": "lower"})
        result = run(
            [{"id": "1", "status": "PAID"}], [{"id": "1", "status": "paid"}], schema
        )
        assert result.is_clean

    def test_without_a_normalizer_case_still_counts(self) -> None:
        schema = build(compare=["status"])
        assert not run(
            [{"id": "1", "status": "PAID"}], [{"id": "1", "status": "paid"}], schema
        ).is_clean


class TestTolerance:
    def test_a_cent_of_rounding_can_be_forgiven(self) -> None:
        schema = build(
            compare=["total"],
            normalizers={"total": "money"},
            tolerances={"total": "0.01"},
        )
        result = run(
            [{"id": "1", "total": "10.00"}], [{"id": "1", "total": "10.01"}], schema
        )
        assert result.is_clean

    def test_beyond_the_tolerance_it_is_still_a_difference(self) -> None:
        schema = build(
            compare=["total"],
            normalizers={"total": "money"},
            tolerances={"total": "0.01"},
        )
        result = run(
            [{"id": "1", "total": "10.00"}], [{"id": "1", "total": "10.02"}], schema
        )
        assert len(result.mismatched) == 1

    def test_tolerance_works_in_both_directions(self) -> None:
        schema = build(
            compare=["total"],
            normalizers={"total": "money"},
            tolerances={"total": Decimal("0.05")},
        )
        result = run(
            [{"id": "1", "total": "10.04"}], [{"id": "1", "total": "10.00"}], schema
        )
        assert result.is_clean

    def test_a_missing_value_is_not_within_tolerance_of_a_number(self) -> None:
        """None and 0.00 are different facts; tolerance must not merge them."""
        schema = build(
            compare=["total"],
            normalizers={"total": "money"},
            tolerances={"total": "1000"},
        )
        result = run(
            [{"id": "1", "total": ""}], [{"id": "1", "total": "10.00"}], schema
        )
        assert len(result.mismatched) == 1


class TestDuplicateKeys:
    def test_a_repeated_key_is_reported_with_its_count(self) -> None:
        result = run(
            [{"id": "1", "total": "10.00", "status": "paid"}] * 3,
            [{"id": "1", "total": "10.00", "status": "paid"}],
        )
        assert result.duplicate_left == {("1",): 3}
        assert result.matched == 1

    def test_duplicates_make_the_result_dirty(self) -> None:
        """Calling this clean would report on a comparison never actually made."""
        rows = [{"id": "1", "total": "10.00", "status": "paid"}]
        result = run(rows * 2, rows)
        assert not result.is_clean

    def test_duplicates_on_the_right_are_caught_too(self) -> None:
        rows = [{"id": "1", "total": "10.00", "status": "paid"}]
        result = run(rows, rows * 4)
        assert result.duplicate_right == {("1",): 4}

    def test_the_first_occurrence_is_the_one_compared(self) -> None:
        left = [{"id": "1", "total": "10.00", "status": "paid"}]
        right = [
            {"id": "1", "total": "10.00", "status": "paid"},
            {"id": "1", "total": "99.00", "status": "void"},
        ]
        result = run(left, right)
        assert result.matched == 1
        assert result.duplicate_right == {("1",): 2}


class TestUnkeyedRows:
    def test_a_row_with_no_key_is_not_counted_as_missing(self) -> None:
        """A broken row must not hide inside "only on the other side"."""
        result = run([{"id": "", "total": "10.00"}], [])
        assert result.only_left == []
        assert len(result.unkeyed_left) == 1
        assert "id" in result.unkeyed_left[0].reason

    def test_a_row_missing_the_key_column_entirely(self) -> None:
        result = run([{"total": "10.00"}], [])
        assert len(result.unkeyed_left) == 1

    def test_unkeyed_rows_are_counted_on_both_sides(self) -> None:
        result = run([{"id": None}], [{"id": "  "}])
        assert len(result.unkeyed_left) == 1
        assert len(result.unkeyed_right) == 1
        assert not result.is_clean


class TestCompositeKeys:
    def test_two_fields_together_form_the_key(self) -> None:
        schema = build(key=["order_id", "line"], compare=["qty"])
        left = [
            {"order_id": "1", "line": "1", "qty": "2"},
            {"order_id": "1", "line": "2", "qty": "5"},
        ]
        right = [
            {"order_id": "1", "line": "1", "qty": "2"},
            {"order_id": "1", "line": "2", "qty": "9"},
        ]
        result = run(left, right, schema)
        assert result.matched == 1
        assert result.mismatched[0].key == ("1", "2")

    def test_the_same_id_on_different_lines_is_not_a_duplicate(self) -> None:
        schema = build(key=["order_id", "line"], compare=[])
        rows = [
            {"order_id": "1", "line": "1"},
            {"order_id": "1", "line": "2"},
        ]
        assert run(rows, rows, schema).is_clean


class TestTotals:
    def test_the_totals_account_for_every_input_row(self) -> None:
        left = [
            {"id": "1", "total": "1", "status": "a"},
            {"id": "1", "total": "1", "status": "a"},
            {"id": "2", "total": "1", "status": "a"},
            {"id": "3", "total": "9", "status": "b"},
            {"id": "", "total": "1", "status": "a"},
        ]
        right = [
            {"id": "1", "total": "1", "status": "a"},
            {"id": "3", "total": "1", "status": "a"},
            {"id": "4", "total": "1", "status": "a"},
        ]
        result = run(left, right)
        assert result.total_left == len(left)
        assert result.total_right == len(right)

    def test_the_summary_is_labelled_with_the_side_names(self) -> None:
        summary = run([], []).summary()
        assert "only_in_erp" in summary
        assert "only_in_shop" in summary


class TestSchemaValidation:
    def test_a_schema_needs_a_key(self) -> None:
        with pytest.raises(SchemaError, match="at least one key"):
            Schema.build(key=[], compare=["total"])

    def test_a_key_field_cannot_also_be_compared(self) -> None:
        """Rows only ever meet when their keys match, so it would check nothing."""
        with pytest.raises(SchemaError, match="cannot also be compared"):
            Schema.build(key=["id"], compare=["id", "total"])

    def test_a_rule_for_an_unknown_field_is_an_error(self) -> None:
        with pytest.raises(SchemaError, match="neither a key nor compared"):
            Schema.build(key=["id"], compare=["total"], normalizers={"typo": "money"})

    def test_a_negative_tolerance_is_rejected(self) -> None:
        with pytest.raises(SchemaError, match="cannot be negative"):
            Schema.build(key=["id"], compare=["total"], tolerances={"total": "-1"})


class TestStreaming:
    def test_the_left_side_is_only_iterated_once(self) -> None:
        """It is streamed, so a one-shot generator has to be enough."""
        consumed = 0

        def generate():
            nonlocal consumed
            for n in range(3):
                consumed += 1
                yield {"id": str(n), "total": "1", "status": "a"}

        result = reconcile(
            generate(),
            [{"id": "0", "total": "1", "status": "a"}],
            build(),
        )
        assert consumed == 3
        assert result.matched == 1
        assert len(result.only_left) == 2
