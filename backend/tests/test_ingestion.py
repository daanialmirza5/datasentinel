import json

import pandas as pd
import pytest

from datasentinel.errors import UnsupportedMediaType, ValidationFailed
from datasentinel.ingestion.inference import infer_column, infer_frame
from datasentinel.ingestion.parser import ParseLimits, detect_format, parse_bytes
from datasentinel.storage import Storage, StorageError

LIMITS = ParseLimits(max_rows=1000, max_columns=20, max_cell_chars=100)


# ---------------------------------------------------------------- parsing


def test_csv_basic_with_null_tokens_and_whitespace():
    parsed = parse_bytes(b"id,name,score\n1, Ada ,9.5\n2,NA,\n3,null,7\n", "csv", LIMITS)
    assert list(parsed.frame.columns) == ["id", "name", "score"]
    assert parsed.frame["name"].tolist() == ["Ada", None, None]
    assert parsed.frame["score"].tolist() == ["9.5", None, "7"]
    assert parsed.rejected_count == 0


def test_csv_rejects_rows_with_wrong_field_count_and_reports_line_numbers():
    content = b"a,b\n1,2\n3\n4,5,6\n7,8\n"
    parsed = parse_bytes(content, "csv", LIMITS)
    assert len(parsed.frame) == 2
    assert parsed.rejected_count == 2
    assert [r.line for r in parsed.rejected] == [3, 4]
    assert "Expected 2 fields" in parsed.rejected[0].reason


def test_csv_sniffs_semicolon_and_tab_delimiters():
    semi = parse_bytes(b"a;b\n1;2\n3;4\n", "csv", LIMITS)
    assert semi.delimiter == ";" and semi.frame.shape == (2, 2)
    tab = parse_bytes(b"a\tb\n1\t2\n", "csv", LIMITS)
    assert tab.delimiter == "\t"


def test_csv_quoted_fields_with_delimiters_and_newlines():
    parsed = parse_bytes(b'id,note\n1,"hello, world"\n2,"multi\nline"\n', "csv", LIMITS)
    assert parsed.frame["note"].tolist() == ["hello, world", "multi\nline"]


def test_duplicate_and_empty_headers_are_repaired_with_warnings():
    parsed = parse_bytes(b"a,a,,b\n1,2,3,4\n", "csv", LIMITS)
    assert list(parsed.frame.columns) == ["a", "a__2", "column_3", "b"]
    assert any("Duplicate column" in w for w in parsed.warnings)
    assert any("empty header" in w for w in parsed.warnings)


def test_blank_lines_are_skipped_and_counted():
    parsed = parse_bytes(b"a,b\n\n1,2\n,\n3,4\n", "csv", LIMITS)
    assert len(parsed.frame) == 2
    assert parsed.blank_lines_skipped == 2


def test_utf8_bom_and_cp1252_fallback():
    bom = parse_bytes("﻿name\nZoë\n".encode(), "csv", LIMITS)
    assert list(bom.frame.columns) == ["name"] and bom.encoding == "utf-8"
    legacy = parse_bytes("name\nCafé\n".encode("cp1252"), "csv", LIMITS)
    assert legacy.encoding == "cp1252"
    assert legacy.frame["name"].tolist() == ["Café"]
    assert any("not valid UTF-8" in w for w in legacy.warnings)


@pytest.mark.parametrize("content", [b"", b"   \n  ", b"\x00\x01binary\x00"])
def test_empty_or_binary_files_are_refused(content):
    with pytest.raises((ValidationFailed, UnsupportedMediaType)):
        parse_bytes(content, "csv", LIMITS)


def test_row_limit_is_enforced():
    content = "x\n" + "\n".join(str(i) for i in range(1001))
    with pytest.raises(ValidationFailed, match="exceeds the configured limit"):
        parse_bytes(content.encode(), "csv", LIMITS)


def test_column_limit_is_enforced():
    header = ",".join(f"c{i}" for i in range(21))
    with pytest.raises(ValidationFailed, match="columns"):
        parse_bytes(f"{header}\n".encode(), "csv", LIMITS)


def test_oversized_cells_reject_the_row():
    parsed = parse_bytes(b"a,b\n1," + b"x" * 101 + b"\n2,ok\n", "csv", LIMITS)
    assert parsed.rejected_count == 1 and len(parsed.frame) == 1


def test_formula_like_values_are_kept_as_inert_text():
    parsed = parse_bytes(b'a\n"=HYPERLINK(""http://x"")"\n@SUM(1)\n', "csv", LIMITS)
    assert parsed.frame["a"].tolist() == ['=HYPERLINK("http://x")', "@SUM(1)"]


def test_json_array_with_nested_objects_and_lists():
    records = [
        {"id": 1, "dims": {"w": 2.5, "deep": {"x": 1}}, "tags": ["a", "b"], "ok": True},
        {"id": 2, "dims": {"w": None}, "ok": False},
    ]
    parsed = parse_bytes(json.dumps(records).encode(), "json", LIMITS)
    assert list(parsed.frame.columns) == ["id", "dims.w", "dims.deep.x", "tags", "ok"]
    assert parsed.frame["tags"].tolist() == ['["a", "b"]', None]
    assert parsed.frame["ok"].tolist() == ["true", "false"]
    assert parsed.frame["dims.deep.x"].tolist() == ["1", None]


def test_json_object_wrapper_and_non_object_records():
    parsed = parse_bytes(b'{"meta": 1, "data": [{"a": 1}, 5, {"a": 2}]}', "json", LIMITS)
    assert parsed.frame["a"].tolist() == ["1", "2"]
    assert parsed.rejected_count == 1
    assert parsed.rejected[0].line == 2


@pytest.mark.parametrize("content", [b"{not json", b'"just a string"', b"[1, 2, 3]", b'{"a": 1}'])
def test_malformed_or_unsupported_json_shapes(content):
    with pytest.raises(ValidationFailed):
        parse_bytes(content, "json", LIMITS)


def test_deeply_nested_json_is_refused_safely():
    content = ("[" * 100000 + "]" * 100000).encode()
    with pytest.raises(ValidationFailed):
        parse_bytes(content, "json", ParseLimits(max_rows=10, max_columns=5, max_cell_chars=10))


def test_jsonl_reports_bad_lines():
    content = b'{"a": 1}\n\n{bad}\n[1]\n{"a": 2, "b": "x"}\n'
    parsed = parse_bytes(content, "jsonl", LIMITS)
    assert parsed.frame["a"].tolist() == ["1", "2"]
    assert parsed.frame["b"].tolist() == [None, "x"]
    assert [r.line for r in parsed.rejected] == [3, 4]
    assert parsed.blank_lines_skipped == 1


def test_detect_format():
    assert detect_format("data.CSV") == "csv"
    assert detect_format("x.ndjson") == "jsonl"
    assert detect_format("anything", "json") == "json"
    with pytest.raises(UnsupportedMediaType):
        detect_format("payload.exe")
    with pytest.raises(UnsupportedMediaType):
        detect_format("x.csv", "xml")


# ---------------------------------------------------------------- inference


def series(values):
    return pd.Series(values, dtype=object)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["1", "2", "-3"], "integer"),
        (["1.5", "2", "3e2"], "float"),
        (["true", "False", "yes", "n"], "boolean"),
        (["0", "1", "1"], "integer"),
        (["2024-01-01", "2024-02-29T10:00:00Z", "2024-03-01 12:30"], "datetime"),
        (["01/31/2024", "12/01/2023"], "datetime"),
        (["alpha", "beta"], "string"),
        ([None, None], "empty"),
        (["00123", "00456"], "string"),
    ],
)
def test_type_inference(values, expected):
    assert infer_column("c", series(values)).inferred_type == expected


def test_invalid_values_counted_when_type_dominates():
    values = [str(i) for i in range(99)] + ["oops"]
    result = infer_column("c", series(values))
    assert result.inferred_type == "integer"
    assert result.invalid_count == 1
    assert result.invalid_examples == ["oops"]


def test_mixed_column_is_flagged_not_coerced():
    values = [str(i) for i in range(70)] + [f"n/a-{i}" for i in range(30)]
    result = infer_column("c", series(values))
    assert result.inferred_type == "string"
    assert result.mixed is True
    assert result.numeric_like_pct == 70.0


def test_unparseable_dates_are_invalid_not_dropped():
    values = [f"2024-01-{i % 28 + 1:02d}" for i in range(99)] + ["2024-13-45"]
    result = infer_column("ts", series(values))
    assert result.inferred_type == "datetime"
    assert result.invalid_count == 1


def test_ambiguous_day_month_is_noted():
    result = infer_column("d", series(["01/02/2024", "03/04/2024", "05/06/2024"]))
    assert result.inferred_type == "datetime"
    assert any("ambiguous" in note for note in result.notes)


def test_typed_frame_preserves_large_integers_and_nulls():
    frame = pd.DataFrame({"id": ["123456789012345678", None, "2"], "flag": ["yes", "no", None]}, dtype=object)
    typed, inferences = infer_frame(frame)
    assert [i.inferred_type for i in inferences] == ["integer", "boolean"]
    assert typed["id"].iloc[0] == 123456789012345678
    assert pd.isna(typed["id"].iloc[1])
    assert typed["flag"].tolist()[:2] == [True, False]


# ---------------------------------------------------------------- storage


def test_storage_rejects_path_traversal(tmp_path):
    storage = Storage(tmp_path)
    for key in ["../evil.csv", "ver_0123456789abcdef.exe", "..\\x.csv", "/etc/passwd", "VER_0123456789ABCDEF.csv"]:
        with pytest.raises(StorageError):
            storage.path_for(key)
    path = storage.write("ver_0123456789abcdef.csv", b"a\n1\n")
    assert path.parent == tmp_path.resolve()
    with pytest.raises(StorageError):
        storage.write("ver_0123456789abcdef.csv", b"overwrite")
    assert storage.read("ver_0123456789abcdef.csv") == b"a\n1\n"


def _nested_list(depth: int):
    root = current = []
    for _ in range(depth):
        child = []
        current.append(child)
        current = child
    return root


def test_rejected_record_preview_survives_extreme_nesting():
    """Regression (seen on Linux / Python 3.14, where json.loads accepts deeper nesting than on
    Windows): previewing a rejected nested record must not raise RecursionError."""
    from datasentinel.ingestion.parser import _preview

    assert "nested too deeply" in _preview(_nested_list(200_000))
    assert _preview([1, 2]) == "[1, 2]"


def test_deeply_nested_field_values_are_refused_cleanly():
    from datasentinel.ingestion.parser import _json_cell

    with pytest.raises(ValidationFailed, match="too deep"):
        _json_cell(_nested_list(200_000), LIMITS)
