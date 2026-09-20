"""The command line, including the exit codes a cron job depends on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reconciler.cli import EXIT_CLEAN, EXIT_DIFFERENCES, EXIT_ERROR, emit, main

LEFT = "id,total,status\n1,10.00,paid\n2,20.00,paid\n3,30.00,paid\n"
MATCHING = LEFT
DIFFERENT = "id,total,status\n1,10.00,paid\n2,99.00,pending\n4,40.00,paid\n"


@pytest.fixture
def files(tmp_path: Path) -> tuple[str, str, str]:
    left = tmp_path / "erp.csv"
    same = tmp_path / "same.csv"
    other = tmp_path / "shop.csv"
    left.write_text(LEFT, encoding="utf-8")
    same.write_text(MATCHING, encoding="utf-8")
    other.write_text(DIFFERENT, encoding="utf-8")
    return str(left), str(same), str(other)


class TestExitCodes:
    def test_agreement_exits_zero(self, files: tuple[str, str, str]) -> None:
        left, same, _ = files
        assert (
            main([left, same, "--key", "id", "--compare", "total,status"]) == EXIT_CLEAN
        )

    def test_differences_exit_one(self, files: tuple[str, str, str]) -> None:
        left, _, other = files
        code = main([left, other, "--key", "id", "--compare", "total,status"])
        assert code == EXIT_DIFFERENCES

    def test_a_missing_file_exits_two_not_one(
        self, files: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A broken run must never look like a clean night to a monitoring job."""
        left, _, _ = files
        assert main([left, "nope.csv", "--key", "id"]) == EXIT_ERROR
        assert "no such file" in capsys.readouterr().err

    def test_an_unknown_normalizer_exits_two(
        self, files: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        left, same, _ = files
        code = main([left, same, "--key", "id", "--normalize", "id=magic"])
        assert code == EXIT_ERROR
        assert "unknown normalizer" in capsys.readouterr().err

    def test_a_malformed_pair_exits_two(self, files: tuple[str, str, str]) -> None:
        left, same, _ = files
        assert (
            main([left, same, "--key", "id", "--normalize", "nonsense"]) == EXIT_ERROR
        )

    def test_failing_can_be_switched_off(self, files: tuple[str, str, str]) -> None:
        left, _, other = files
        code = main(
            [
                left,
                other,
                "--key",
                "id",
                "--compare",
                "total",
                "--no-fail-on-difference",
            ]
        )
        assert code == EXIT_CLEAN


class TestOutput:
    def test_the_default_output_is_human_readable(
        self, files: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        left, _, other = files
        main([left, other, "--key", "id", "--compare", "total"])
        out = capsys.readouterr().out
        assert "Reconciliation:" in out
        assert "erp.csv" in out

    def test_json_output_is_machine_readable(
        self, files: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        left, _, other = files
        main([left, other, "--key", "id", "--compare", "total", "--format", "json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["mismatched"] == 1

    def test_it_can_write_to_a_file(
        self, files: tuple[str, str, str], tmp_path: Path
    ) -> None:
        left, _, other = files
        target = tmp_path / "report.md"
        main(
            [
                left,
                other,
                "--key",
                "id",
                "--compare",
                "total",
                "--format",
                "markdown",
                "--output",
                str(target),
            ]
        )
        assert "## Reconciliation" in target.read_text(encoding="utf-8")

    def test_the_side_labels_can_be_overridden(
        self, files: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        left, _, other = files
        main([left, other, "--key", "id", "--left-name", "ERP", "--right-name", "Loja"])
        assert "ERP vs Loja" in capsys.readouterr().out


class TestOptions:
    def test_normalizers_and_tolerances_reach_the_comparison(
        self, tmp_path: Path
    ) -> None:
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        # The same order as two different systems export it: zero-padded id
        # and Brazilian money on one side, plain on the other.
        a.write_text('id,total\n00042,"1.234,50"\n', encoding="utf-8")
        b.write_text("id,total\n42,1234.5\n", encoding="utf-8")

        code = main(
            [
                str(a),
                str(b),
                "--key",
                "id",
                "--compare",
                "total",
                "--normalize",
                "id=integer",
                "--normalize",
                "total=money",
            ]
        )
        assert code == EXIT_CLEAN

    def test_tolerance_forgives_a_rounding_cent(self, tmp_path: Path) -> None:
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        a.write_text("id,total\n1,10.00\n", encoding="utf-8")
        b.write_text("id,total\n1,10.01\n", encoding="utf-8")

        assert (
            main(
                [
                    str(a),
                    str(b),
                    "--key",
                    "id",
                    "--compare",
                    "total",
                    "--normalize",
                    "total=money",
                ]
            )
            == EXIT_DIFFERENCES
        )
        assert (
            main(
                [
                    str(a),
                    str(b),
                    "--key",
                    "id",
                    "--compare",
                    "total",
                    "--normalize",
                    "total=money",
                    "--tolerance",
                    "total=0.01",
                ]
            )
            == EXIT_CLEAN
        )

    def test_a_custom_delimiter(self, tmp_path: Path) -> None:
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        a.write_text("id;total\n1;10\n", encoding="utf-8")
        b.write_text("id;total\n1;10\n", encoding="utf-8")
        assert (
            main(
                [
                    str(a),
                    str(b),
                    "--key",
                    "id",
                    "--compare",
                    "total",
                    "--delimiter",
                    ";",
                ]
            )
            == EXIT_CLEAN
        )

    def test_json_input_is_detected_by_extension(self, tmp_path: Path) -> None:
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        a.write_text(json.dumps([{"id": "1", "total": "10"}]), encoding="utf-8")
        b.write_text(json.dumps([{"id": "1", "total": "10"}]), encoding="utf-8")
        assert main([str(a), str(b), "--key", "id", "--compare", "total"]) == EXIT_CLEAN


class TestConsoleEncoding:
    def test_a_console_that_cannot_spell_the_report_still_gets_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A legacy Windows code page must degrade the output, not kill the run."""
        import io
        import sys

        class NarrowConsole(io.StringIO):
            def write(self, text: str) -> int:
                if any(ord(char) > 127 for char in text):
                    raise UnicodeEncodeError("charmap", text, 0, 1, "unmappable")
                return super().write(text)

        console = NarrowConsole()
        monkeypatch.setattr(sys, "stdout", console)
        emit("status: ❌ 5 problem(s)", None)

        written = console.getvalue()
        assert "5 problem(s)" in written
        assert "❌" not in written

    def test_file_output_keeps_the_characters_intact(self, tmp_path: Path) -> None:
        target = tmp_path / "report.md"
        emit("status: ❌ failed", str(target))
        assert "❌" in target.read_text(encoding="utf-8")
