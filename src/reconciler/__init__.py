"""reconciliation-report: find every way two systems disagree about the same data.

Point it at two exports, say which field is the key and which fields matter, and
it tells you what is missing from each side, what disagrees, which keys appear
twice and which rows cannot be keyed at all.
"""

from reconciler.core import (
    Difference,
    Mismatch,
    Reconciliation,
    Unkeyed,
    iter_problems,
    reconcile,
)
from reconciler.normalizers import BY_NAME, Normalizer, resolve
from reconciler.report import as_csv, as_json, as_markdown, as_text
from reconciler.schema import Field, Key, Schema, SchemaError, format_key
from reconciler.sources import (
    CallableSource,
    CsvSource,
    IterableSource,
    JsonSource,
    Record,
    Source,
)

__version__ = "0.1.0"

__all__ = [
    "BY_NAME",
    "CallableSource",
    "CsvSource",
    "Difference",
    "Field",
    "IterableSource",
    "JsonSource",
    "Key",
    "Mismatch",
    "Normalizer",
    "Reconciliation",
    "Record",
    "Schema",
    "SchemaError",
    "Source",
    "Unkeyed",
    "__version__",
    "as_csv",
    "as_json",
    "as_markdown",
    "as_text",
    "format_key",
    "iter_problems",
    "reconcile",
    "resolve",
]
