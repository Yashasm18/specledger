"""Safe ingestion primitives for messy industrial catalogue files.

This module deliberately stops before enrichment. It turns a source table into
stable, traceable rows so later matching and generation can be deterministic.
It accepts CSV/TSV and optionally XLSX when ``openpyxl`` is installed.
"""

from __future__ import annotations

import csv
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
            key = canonical_key(str(raw_key))
            if key and key not in columns:
                columns.append(key)
    if not columns:
        raise ValueError("Catalogue file contains no usable columns")
    normalized: list[SourceRow] = []
    for number, row in enumerate(materialized, start=2):
        values = {canonical_key(str(key)): clean_cell(value) for key, value in row.items() if canonical_key(str(key))}
        values = {column: values.get(column) for column in columns}
        normalized.append(SourceRow(number, source_name, row_fingerprint(values), values))
    return CatalogueBatch(source_name, tuple(columns), tuple(normalized))


def read_catalogue(path: str | Path, sheet_name: str | None = None) -> CatalogueBatch:
    """Read CSV, TSV, or XLSX into the normalized batch contract."""
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix in {".csv", ".tsv"}:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            delimiter = "\t" if suffix == ".tsv" else ","
            return normalize_rows(source.name, csv.DictReader(handle, delimiter=delimiter))
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
