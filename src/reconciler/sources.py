"""Where the two sides come from.

A source is anything that yields dictionaries. That deliberately small contract
is what lets the same reconciliation run against a CSV export today and against
a database cursor or a paginated API tomorrow, without the comparison code
learning anything about either.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

Record = Mapping[str, Any]


class Source(Protocol):
    """Yields records. Iterating twice is allowed but never required."""

    name: str

    def __iter__(self) -> Iterator[Record]: ...


@dataclass
class IterableSource:
    """Wraps anything already in memory, or any generator.

    This is the adapter for a database cursor or an API client: hand it a
    generator and the reconciler never learns where the rows came from.
    """

    records: Iterable[Record]
    name: str = "iterable"

    def __iter__(self) -> Iterator[Record]:
        return iter(self.records)


@dataclass
class CallableSource:
    """A source that is re-fetched every time it is iterated."""

    factory: Callable[[], Iterable[Record]]
    name: str = "callable"

    def __iter__(self) -> Iterator[Record]:
        return iter(self.factory())


@dataclass
class CsvSource:
    """A delimited text file, read one row at a time.

    Rows are streamed rather than loaded, so the side that gets streamed can be
    much larger than memory. The file is opened per iteration, which keeps the
    source reusable and avoids leaving a handle open for the whole run.
    """

    path: Path | str
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    name: str = ""

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if not self.name:
            self.name = self.path.name

    def __iter__(self) -> Iterator[Record]:
        with open(self.path, newline="", encoding=self.encoding) as handle:
            reader = csv.DictReader(handle, delimiter=self.delimiter)
            if reader.fieldnames is None:
                return
            for row in reader:
                # DictReader puts surplus columns under None; dropping the key
                # keeps every record a clean str->value mapping.
                row.pop(None, None)
                yield row

    @property
    def columns(self) -> list[str]:
        with open(self.path, newline="", encoding=self.encoding) as handle:
            return next(csv.reader(handle, delimiter=self.delimiter), [])


@dataclass
class JsonSource:
    """A JSON array of objects, or a JSON Lines file.

    JSON Lines is detected by trying to parse the first non-blank line on its
    own; an export is one or the other and guessing wrong is loud, not subtle.
    """

    path: Path | str
    records_key: str | None = None
    encoding: str = "utf-8"
    name: str = ""

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if not self.name:
            self.name = self.path.name

    def __iter__(self) -> Iterator[Record]:
        text = Path(self.path).read_text(encoding=self.encoding)
        stripped = text.lstrip()
        if stripped.startswith("["):
            yield from json.loads(text)
            return
        if stripped.startswith("{") and self._is_single_document(stripped):
            document = json.loads(text)
            if self.records_key:
                yield from document[self.records_key]
            else:
                yield document
            return
        for line in text.splitlines():
            if line.strip():
                yield json.loads(line)

    @staticmethod
    def _is_single_document(text: str) -> bool:
        try:
            json.loads(text)
        except json.JSONDecodeError:
            return False
        return True
