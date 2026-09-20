"""Reading CSV and JSON."""

from __future__ import annotations

import json
from pathlib import Path

from reconciler import CallableSource, CsvSource, IterableSource, JsonSource


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestCsv:
    def test_rows_become_dictionaries(self, tmp_path: Path) -> None:
        path = write(tmp_path, "a.csv", "id,total\n1,10.00\n2,20.00\n")
        assert list(CsvSource(path)) == [
            {"id": "1", "total": "10.00"},
            {"id": "2", "total": "20.00"},
        ]

    def test_the_source_can_be_iterated_more_than_once(self, tmp_path: Path) -> None:
        """The file is reopened each time, so a source is not single-use."""
        path = write(tmp_path, "a.csv", "id\n1\n")
        source = CsvSource(path)
        assert list(source) == list(source)

    def test_a_bom_does_not_corrupt_the_first_column_name(self, tmp_path: Path) -> None:
        """Excel writes a BOM, which otherwise turns 'id' into a key nothing matches."""
        path = tmp_path / "bom.csv"
        path.write_bytes(b"\xef\xbb\xbfid,total\n1,10\n")
        assert next(iter(CsvSource(path)))["id"] == "1"

    def test_a_custom_delimiter(self, tmp_path: Path) -> None:
        path = write(tmp_path, "a.csv", "id;total\n1;10,00\n")
        assert list(CsvSource(path, delimiter=";")) == [{"id": "1", "total": "10,00"}]

    def test_a_header_only_file_yields_nothing(self, tmp_path: Path) -> None:
        path = write(tmp_path, "a.csv", "id,total\n")
        assert list(CsvSource(path)) == []

    def test_an_empty_file_yields_nothing(self, tmp_path: Path) -> None:
        path = write(tmp_path, "a.csv", "")
        assert list(CsvSource(path)) == []

    def test_surplus_columns_do_not_leave_a_none_key(self, tmp_path: Path) -> None:
        path = write(tmp_path, "a.csv", "id\n1,extra,more\n")
        (row,) = list(CsvSource(path))
        assert None not in row

    def test_the_name_defaults_to_the_file_name(self, tmp_path: Path) -> None:
        assert CsvSource(write(tmp_path, "erp.csv", "id\n")).name == "erp.csv"

    def test_columns_can_be_inspected_without_reading_the_body(
        self, tmp_path: Path
    ) -> None:
        path = write(tmp_path, "a.csv", "id,total,status\n1,10,paid\n")
        assert CsvSource(path).columns == ["id", "total", "status"]


class TestJson:
    def test_an_array_of_objects(self, tmp_path: Path) -> None:
        path = write(tmp_path, "a.json", json.dumps([{"id": 1}, {"id": 2}]))
        assert list(JsonSource(path)) == [{"id": 1}, {"id": 2}]

    def test_json_lines(self, tmp_path: Path) -> None:
        path = write(tmp_path, "a.jsonl", '{"id": 1}\n{"id": 2}\n')
        assert list(JsonSource(path)) == [{"id": 1}, {"id": 2}]

    def test_blank_lines_in_json_lines_are_skipped(self, tmp_path: Path) -> None:
        path = write(tmp_path, "a.jsonl", '{"id": 1}\n\n{"id": 2}\n')
        assert len(list(JsonSource(path))) == 2

    def test_records_nested_under_a_key(self, tmp_path: Path) -> None:
        """The shape most paginated APIs return."""
        body = json.dumps({"count": 2, "results": [{"id": 1}, {"id": 2}]})
        path = write(tmp_path, "a.json", body)
        assert list(JsonSource(path, records_key="results")) == [{"id": 1}, {"id": 2}]


class TestInMemory:
    def test_an_iterable_is_a_source(self) -> None:
        assert list(IterableSource([{"id": 1}])) == [{"id": 1}]

    def test_a_callable_source_refetches_each_time(self) -> None:
        """The adapter shape for a database cursor or an API client."""
        calls = 0

        def fetch() -> list[dict[str, int]]:
            nonlocal calls
            calls += 1
            return [{"id": calls}]

        source = CallableSource(fetch)
        assert list(source) == [{"id": 1}]
        assert list(source) == [{"id": 2}]
