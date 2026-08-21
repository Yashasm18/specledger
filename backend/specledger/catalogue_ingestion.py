"""Safe ingestion primitives for messy industrial catalogue files.

This module deliberately stops before enrichment. It turns a source table into
stable, traceable rows so later matching and generation can be deterministic.
It accepts CSV/TSV and optionally XLSX when ``openpyxl`` is installed.
"""

from __future__ import annotations

import csv
import io
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


PLACEHOLDERS = frozenset({"", "-", "--", "n/a", "na", "none", "null", "unknown"})


def canonical_key(value: str) -> str:
    """Create a stable comparison key without destroying the source value."""
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def clean_cell(value: object) -> str | None:
    """Normalize whitespace and remove known placeholder values."""
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value).replace("\u00a0", " ")).strip()
    return None if cleaned.casefold() in PLACEHOLDERS else cleaned


def clean_manufacturer_name(raw_name: str | None) -> str | None:
    """Strip distributor codes in parentheses, e.g. 'Freud Inc (2435)' -> 'Freud Inc'."""
    if not raw_name:
        return None
    # Remove code in trailing parentheses like (2435) or (JAMIN)
    cleaned = re.sub(r"\s*\([A-Z0-9_-]+\)\s*$", "", raw_name.strip(), flags=re.IGNORECASE).strip()
    return cleaned if cleaned else raw_name



@dataclass(frozen=True)
class SourceRow:
    row_number: int
    source_name: str
    source_fingerprint: str
    values: dict[str, str | None]


@dataclass(frozen=True)
class CatalogueBatch:
    source_name: str
    columns: tuple[str, ...]
    rows: tuple[SourceRow, ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)


def row_fingerprint(values: Mapping[str, str | None]) -> str:
    payload = json.dumps(dict(sorted(values.items())), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_rows(source_name: str, rows: Iterable[Mapping[object, object]]) -> CatalogueBatch:
    """Normalize headers/cells while retaining row-level lineage."""
    materialized = list(rows)
    if not materialized:
        raise ValueError("Catalogue file contains no data rows")
    columns: list[str] = []
    for row in materialized:
        for raw_key in row:
            # csv.DictReader files any fields beyond the header under a None
            # key, as a list. Those have no column name, so they are not a
            # column — treating them as one produced a phantom "none" column
            # holding a stringified Python list, which would then be carried
            # into the delivered 252-column export.
            if raw_key is None:
                continue
            key = canonical_key(str(raw_key))
            if key and key not in columns:
                columns.append(key)
    if not columns:
        raise ValueError("Catalogue file contains no usable columns")
    normalized: list[SourceRow] = []
    for number, row in enumerate(materialized, start=2):
        values = {
            canonical_key(str(key)): clean_cell(value)
            for key, value in row.items()
            if key is not None and canonical_key(str(key))
        }
        values = {column: values.get(column) for column in columns}
        # Skip rows that are entirely empty. Spreadsheets routinely carry
        # trailing blank rows, and a CSV can end with a stray newline; each
        # would otherwise become a product with no part number and no
        # description — a phantom SKU in the delivered catalogue.
        #
        # The counter still advances, so row numbers keep pointing at the
        # line they came from in the uploaded file. Lineage is the point.
        if not any(value for value in values.values()):
            continue
        normalized.append(SourceRow(number, source_name, row_fingerprint(values), values))
    if not normalized:
        raise ValueError("Catalogue file contains no data rows")
    return CatalogueBatch(source_name, tuple(columns), tuple(normalized))


# Encodings tried in order when reading a delimited file. UTF-8 covers most
# exports; cp1252 is what Excel on Windows writes by default, which is a very
# common way for a real catalogue to arrive. Latin-1 accepts any byte
# sequence, so it is last and only prevents a hard failure.
_TEXT_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def _decode_text(source: Path) -> str:
    """Read a delimited file, tolerating non-UTF-8 exports.

    Decoding as UTF-8 only meant a spreadsheet saved from Excel on Windows
    failed with a raw codec error naming a byte offset — accurate, and
    useless to whoever uploaded it.
    """
    raw = source.read_bytes()
    for encoding in _TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(
        "Could not decode this file as text. Save it as UTF-8 CSV "
        "(or upload the .xlsx directly) and try again."
    )


def read_catalogue(path: str | Path, sheet_name: str | None = None) -> CatalogueBatch:
    """Read CSV, TSV, or XLSX into the normalized batch contract."""
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        text = _decode_text(source)
        return normalize_rows(
            source.name, csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
        )
    if suffix == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("XLSX ingestion requires the openpyxl dependency") from exc
        workbook = load_workbook(source, read_only=True, data_only=True)
        worksheet = workbook[sheet_name] if sheet_name else workbook.active
        records = worksheet.iter_rows(values_only=True)
        headers = next(records, None)
        if not headers:
            raise ValueError("XLSX sheet contains no header row")
        return normalize_rows(source.name, (dict(zip(headers, values)) for values in records))
    raise ValueError("Unsupported catalogue format; use CSV, TSV, or XLSX")
