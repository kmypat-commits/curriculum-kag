import io
import zipfile

import pytest

from app.services.university_baseline_import import (
    ImportValidationError,
    canonical_hash,
    parse_source,
    validate_mapping,
)


def test_utf8_csv_requires_explicit_columns_and_preserves_rows():
    data = "code,title,credits\nCS-1,Алгоритмы,5\nCS-1,Алгоритмы (повтор),3\n".encode()
    rows = parse_source(data, "baseline.csv", {"code": "code", "title": "title", "credits": "credits"})
    assert [row["original_code"] for row in rows] == ["CS-1", "CS-1"]
    assert [row["credits"] for row in rows] == [5.0, 3.0]


def test_missing_column_is_rejected():
    with pytest.raises(ImportValidationError, match="missing"):
        parse_source(b"code,title\nCS-1,Algorithms\n", "baseline.csv", {"code": "code", "title": "title", "credits": "credits"})


def test_invalid_credits_are_rejected():
    with pytest.raises(ImportValidationError, match="credits"):
        parse_source(b"code,title,credits\nCS-1,Algorithms,0\n", "baseline.csv", {"code": "code", "title": "title", "credits": "credits"})


def test_oversized_xlsx_archive_is_rejected_before_openpyxl():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"x" * (100 * 1024 * 1024 + 1))
    with pytest.raises(ImportValidationError, match="uncompressed"):
        parse_source(stream.getvalue(), "baseline.xlsx", {"code": "code", "title": "title", "credits": "credits"})


def test_mapping_requires_every_source_row_and_known_catalogue_id():
    rows = [{"source_row": 2, "original_code": "CS-1", "original_title": "Algorithms", "credits": 5.0}]
    with pytest.raises(ImportValidationError, match="mapping"):
        validate_mapping(rows, {}, {10: {"code": "CS-1", "title": "Algorithms"}})


def test_canonical_hash_is_order_stable_for_same_rows():
    rows = [{"source_row": 2, "original_code": "CS-1", "credits": 5.0}]
    assert canonical_hash(rows) == canonical_hash(list(rows))
