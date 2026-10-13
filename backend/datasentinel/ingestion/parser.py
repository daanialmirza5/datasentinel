"""Safe parsing of CSV, JSON and JSON Lines uploads into a table of strings.

Design notes
------------
* Content is only ever *parsed*, never evaluated. CSV goes through the standard library ``csv``
  module, JSON through ``json`` with a recursion guard. No pickle, no ``eval``, no formula
  evaluation, no remote references.
* Every cell becomes either ``None`` (missing) or a stripped string. Type inference happens in a
  separate step (see ``inference.py``) so that the same rules apply to every format.
* Malformed rows are *rejected and reported* rather than silently dropped or coerced: each rejected
  row keeps its 1-based line number (CSV/JSONL) or record index (JSON) and a reason.
* Limits (rows, columns, cell length) are enforced while parsing so a hostile file cannot exhaust
  memory before being refused.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from datasentinel.errors import UnsupportedMediaType, ValidationFailed

SUPPORTED_FORMATS = {"csv", "json", "jsonl"}
EXTENSION_FORMATS = {".csv": "csv", ".tsv": "csv", ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl"}

# Values treated as missing. Matching is exact after stripping whitespace (case-sensitive set
# below covers common spellings) so a legitimate value such as "Nana" is never nulled.
NULL_TOKENS = frozenset(
    {"", "NA", "N/A", "n/a", "na", "NaN", "nan", "NULL", "null", "Null", "None", "none", "#N/A", "-", "--", "?"}
)
MAX_COLUMN_NAME_LENGTH = 128
MAX_REJECTED_ROWS_KEPT = 500
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_MAX_JSON_FLATTEN_DEPTH = 3


@dataclass(frozen=True)
class ParseLimits:
    max_rows: int = 200_000
    max_columns: int = 200
    max_cell_chars: int = 10_000


@dataclass
class RejectedRow:
    line: int
    reason: str
    preview: str

    def as_dict(self) -> dict[str, Any]:
        return {"line": self.line, "reason": self.reason, "preview": self.preview}


@dataclass
class ParsedTable:
    frame: pd.DataFrame  # object dtype; cells are str or None
    file_format: str
    encoding: str = "utf-8"
    delimiter: str | None = None
    rejected: list[RejectedRow] = field(default_factory=list)
    rejected_count: int = 0
    blank_lines_skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    column_renames: dict[str, str] = field(default_factory=dict)

    def reject(self, line: int, reason: str, raw: str) -> None:
        self.rejected_count += 1
        if len(self.rejected) < MAX_REJECTED_ROWS_KEPT:
            self.rejected.append(RejectedRow(line, reason, raw[:200]))


def detect_format(filename: str, explicit: str | None = None) -> str:
    if explicit:
        fmt = explicit.lower().strip()
        if fmt not in SUPPORTED_FORMATS:
            raise UnsupportedMediaType(f"Unsupported format '{explicit}'. Supported: csv, json, jsonl.")
        return fmt
    lowered = filename.lower()
    for ext, fmt in EXTENSION_FORMATS.items():
        if lowered.endswith(ext):
            return fmt
    raise UnsupportedMediaType(
        "Unsupported file type. Upload a .csv, .tsv, .json, .jsonl or .ndjson file.",
        details={"filename": filename},
    )


def _decode(content: bytes, warnings: list[str]) -> tuple[str, str]:
    if not content.strip():
        raise ValidationFailed("The file is empty.")
    if b"\x00" in content[:8192]:
        raise UnsupportedMediaType("The file looks binary (contains NUL bytes); only text formats are accepted.")
    try:
        return content.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        text = content.decode("cp1252")
        warnings.append("File is not valid UTF-8; decoded as Windows-1252. Check special characters.")
        return text, "cp1252"
    except UnicodeDecodeError:
        warnings.append("File is not valid UTF-8; decoded as Latin-1. Check special characters.")
        return content.decode("latin-1"), "latin-1"


def normalise_column_names(raw_names: list[str], warnings: list[str]) -> tuple[list[str], dict[str, str]]:
    """Validate and repair column names. Returns (names, {original: repaired})."""
    names: list[str] = []
    renames: dict[str, str] = {}
    seen: set[str] = set()
    for index, raw in enumerate(raw_names):
        original = raw if isinstance(raw, str) else str(raw)
        name = _CONTROL_CHARS.sub("", original).strip()
        if not name:
            name = f"column_{index + 1}"
            warnings.append(f"Column {index + 1} has an empty header; named it '{name}'.")
        if len(name) > MAX_COLUMN_NAME_LENGTH:
            name = name[:MAX_COLUMN_NAME_LENGTH]
            warnings.append(
                f"Column {index + 1} header was longer than {MAX_COLUMN_NAME_LENGTH} characters and was truncated."
            )
        base, suffix = name, 2
        while name in seen:
            name = f"{base}__{suffix}"
            suffix += 1
        if name != base:
            warnings.append(f"Duplicate column name '{base}' renamed to '{name}'.")
        seen.add(name)
        if name != original:
            renames[original] = name
        names.append(name)
    return names, renames


def _clean_cell(value: str) -> str | None:
    stripped = value.strip()
    return None if stripped in NULL_TOKENS else stripped


def _check_row_limit(count: int, limits: ParseLimits) -> None:
    if count > limits.max_rows:
        raise ValidationFailed(
            f"The file has more than {limits.max_rows} data rows, which exceeds the configured limit.",
            details={"max_rows": limits.max_rows},
        )


def _check_columns(names: list[str], limits: ParseLimits) -> None:
    if not names:
        raise ValidationFailed("No columns found. The first non-empty line must be a header row.")
    if len(names) > limits.max_columns:
        raise ValidationFailed(
            f"The file has {len(names)} columns; the limit is {limits.max_columns}.",
            details={"max_columns": limits.max_columns},
        )


def parse_csv(text: str, limits: ParseLimits, result: ParsedTable) -> None:
    sample = text[:16384]
    delimiter = ","
    with contextlib.suppress(csv.Error):
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    result.delimiter = delimiter

    csv.field_size_limit(max(limits.max_cell_chars * 4, 131072))
    lines = io.StringIO(text, newline="")
    reader = csv.reader(lines, delimiter=delimiter, strict=False)

    header: list[str] | None = None
    rows: list[list[str | None]] = []
    while True:
        try:
            raw_row = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            result.reject(reader.line_num, f"Malformed CSV: {exc}", "")
            continue
        line = reader.line_num
        if not raw_row or all(not cell.strip() for cell in raw_row):
            result.blank_lines_skipped += 1
            continue
        if header is None:
            header, result.column_renames = normalise_column_names(raw_row, result.warnings)
            _check_columns(header, limits)
            if all(re.fullmatch(r"[+-]?\d+(\.\d+)?", h) for h in header):
                result.warnings.append("The header row contains only numbers; the file may be missing a header.")
            continue
        if len(raw_row) != len(header):
            result.reject(line, f"Expected {len(header)} fields, found {len(raw_row)}", delimiter.join(raw_row))
            continue
        if any(len(cell) > limits.max_cell_chars for cell in raw_row):
            result.reject(line, f"A cell exceeds {limits.max_cell_chars} characters", delimiter.join(raw_row))
            continue
        rows.append([_clean_cell(cell) for cell in raw_row])
        _check_row_limit(len(rows), limits)

    if header is None:
        raise ValidationFailed("No header row found; the file contains no data.")
    result.frame = pd.DataFrame(rows, columns=header, dtype=object)


def _flatten(record: dict[str, Any], prefix: str = "", depth: int = 0) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in record.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and depth < _MAX_JSON_FLATTEN_DEPTH:
            flat.update(_flatten(value, name, depth + 1))
        else:
            flat[name] = value
    return flat


def _json_cell(value: Any, limits: ParseLimits) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        text = repr(value) if isinstance(value, float) else str(value)
    elif isinstance(value, str):
        return _clean_cell(value) if len(value) <= limits.max_cell_chars else value
    else:  # lists, deeply nested objects
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except RecursionError as exc:
            # How deep json.loads can go depends on the platform's C stack, so encoding is guarded too.
            raise ValidationFailed("JSON nesting is too deep.") from exc
    return text


def _preview(item: Any) -> str:
    """Short text preview of a rejected JSON value that cannot fail on deeply nested input."""
    try:
        return json.dumps(item)[:200]
    except (RecursionError, ValueError):
        return f"<{type(item).__name__} nested too deeply to preview>"


def _records_to_frame(records: list[tuple[int, dict[str, Any]]], limits: ParseLimits, result: ParsedTable) -> None:
    columns: list[str] = []
    seen: set[str] = set()
    flat_records: list[tuple[int, dict[str, Any]]] = []
    for index, record in records:
        flat = _flatten(record)
        too_long = next((k for k, v in flat.items() if isinstance(v, str) and len(v) > limits.max_cell_chars), None)
        if too_long is not None:
            result.reject(index, f"Field '{too_long}' exceeds {limits.max_cell_chars} characters", "")
            continue
        for key in flat:
            if key not in seen:
                seen.add(key)
                columns.append(key)
        flat_records.append((index, flat))
    names, renames = normalise_column_names(columns, result.warnings)
    result.column_renames = renames
    _check_columns(names, limits)
    missing_keys = 0
    rows: list[list[str | None]] = []
    for _, flat in flat_records:
        row = []
        for original in columns:
            if original not in flat:
                missing_keys += 1
            row.append(_json_cell(flat.get(original), limits))
        rows.append(row)
    if missing_keys:
        result.warnings.append(f"{missing_keys} field(s) were absent from some records and are treated as missing.")
    result.frame = pd.DataFrame(rows, columns=names, dtype=object)


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except RecursionError as exc:
        raise ValueError("JSON nesting is too deep") from exc


def parse_json(text: str, limits: ParseLimits, result: ParsedTable) -> None:
    try:
        document = _loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValidationFailed(f"Malformed JSON: {exc}") from exc
    if isinstance(document, dict):
        lists = [(k, v) for k, v in document.items() if isinstance(v, list)]
        preferred = [item for item in lists if item[0] in ("data", "records", "rows", "items")]
        if len(preferred) == 1:
            lists = preferred
        if len(lists) != 1:
            raise ValidationFailed(
                "JSON must be an array of objects, or an object containing exactly one array of records "
                '(for example {"data": [...]}).'
            )
        result.warnings.append(f"Records were read from the '{lists[0][0]}' key.")
        document = lists[0][1]
    if not isinstance(document, list):
        raise ValidationFailed("JSON must be an array of objects.")
    _check_row_limit(len(document), limits)
    records: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(document, start=1):
        if isinstance(item, dict):
            records.append((index, item))
        else:
            result.reject(index, f"Record is a {type(item).__name__}, not an object", _preview(item))
    if not records:
        raise ValidationFailed("The JSON array contains no objects.")
    _records_to_frame(records, limits, result)


def parse_jsonl(text: str, limits: ParseLimits, result: ParsedTable) -> None:
    records: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            result.blank_lines_skipped += 1
            continue
        try:
            item = _loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            result.reject(line_number, f"Invalid JSON: {exc}", line)
            continue
        if not isinstance(item, dict):
            result.reject(line_number, f"Line is a {type(item).__name__}, not an object", line)
            continue
        records.append((line_number, item))
        _check_row_limit(len(records), limits)
    if not records:
        raise ValidationFailed(
            "No valid JSON objects found in the JSON Lines file.",
            details={"rejected": [r.as_dict() for r in result.rejected[:20]]},
        )
    _records_to_frame(records, limits, result)


def parse_bytes(content: bytes, file_format: str, limits: ParseLimits) -> ParsedTable:
    result = ParsedTable(frame=pd.DataFrame(), file_format=file_format)
    text, result.encoding = _decode(content, result.warnings)
    if file_format == "csv":
        parse_csv(text, limits, result)
    elif file_format == "json":
        parse_json(text, limits, result)
    elif file_format == "jsonl":
        parse_jsonl(text, limits, result)
    else:  # pragma: no cover - guarded by detect_format
        raise UnsupportedMediaType(f"Unsupported format '{file_format}'")
    return result
