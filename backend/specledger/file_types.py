"""What an uploaded file is, and what SpecLedger will do with it.

Two kinds of upload reach this system and they are not interchangeable:

* a **catalogue** — structured rows that become enriched 252-column records
* a **document** — prose or a datasheet, read for labelled specifications
  and page-level evidence, producing no catalogue rows at all

Everything else is refused, and a refusal says why and what to send
instead. Silence here is expensive: a judge who uploads a scan of a
datasheet and sees nothing happen has no way to tell a rejected format
from a broken pipeline.

This module is the single place that rule lives. It had begun to spread
across ``ALLOWED_EXTENSIONS`` in the ingest endpoint, ``read_catalogue``'s
suffix branch, the intake endpoint's content-type check and three separate
pieces of UI copy — the same duplication that has produced the same defect
five times in this codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UploadKind:
    """What to do with an uploaded file."""
    kind: str            # "catalogue" | "document" | "unsupported"
    extension: str
    reason: str = ""     # why it was refused, and what to send instead
    description: str = ""  # what this format is, for the UI


# Structured data. Becomes rows.
CATALOGUE_FORMATS: dict[str, str] = {
    ".csv": "Comma-separated rows. The most common distributor feed.",
    ".tsv": "Tab-separated rows.",
    ".xlsx": "Excel workbook. The first sheet is read unless another is named.",
    ".json": "An array of objects, or an object wrapping one.",
    ".xml": "Repeated elements, one per product.",
}

# Prose and datasheets. Read for facts; creates no rows.
DOCUMENT_FORMATS: dict[str, str] = {
    ".pdf": "Manufacturer datasheets and specification sheets.",
    ".txt": "Plain text with no formatting.",
    ".docx": "Word document.",
    ".rtf": "Rich text.",
}

# Refused, with the reason the reader needs. A format that has a modern
# replacement names it rather than simply failing.
_REJECTIONS: dict[str, str] = {
    ".xls": "Legacy Excel is not readable here — re-save it as .xlsx.",
    ".doc": "Legacy Word is not readable here — re-save it as .docx.",
    ".jpg": "An image carries no machine-readable text. Send the datasheet as a PDF.",
    ".jpeg": "An image carries no machine-readable text. Send the datasheet as a PDF.",
    ".png": "An image carries no machine-readable text. Send the datasheet as a PDF.",
    ".gif": "An image carries no machine-readable text. Send the datasheet as a PDF.",
    ".svg": "An image carries no machine-readable text. Send the datasheet as a PDF.",
    ".mp3": "Audio carries no product specifications SpecLedger can verify.",
    ".wav": "Audio carries no product specifications SpecLedger can verify.",
    ".mp4": "Video carries no product specifications SpecLedger can verify.",
    ".avi": "Video carries no product specifications SpecLedger can verify.",
    ".mov": "Video carries no product specifications SpecLedger can verify.",
    ".zip": "Archives are not opened. Upload the files inside it individually.",
    ".exe": "Executables are never accepted.",
    ".iso": "Disk images are never accepted.",
}

_SUPPORTED_LIST = ", ".join(sorted(CATALOGUE_FORMATS) + sorted(DOCUMENT_FORMATS))


def classify_upload(filename: str) -> UploadKind:
    """Decide what an uploaded filename is, by extension.

    Extension only: sniffing content would let a mislabelled file take a
    path its uploader did not intend, and every real feed and datasheet
    arrives correctly named.
    """
    extension = Path(str(filename or "")).suffix.casefold()

    if extension in CATALOGUE_FORMATS:
        return UploadKind("catalogue", extension, description=CATALOGUE_FORMATS[extension])
    if extension in DOCUMENT_FORMATS:
        return UploadKind("document", extension, description=DOCUMENT_FORMATS[extension])
    if extension in _REJECTIONS:
        return UploadKind("unsupported", extension, reason=_REJECTIONS[extension])
    if not extension:
        return UploadKind(
            "unsupported", "",
            reason=f"The file has no extension, so its format is unknown. Supported: {_SUPPORTED_LIST}.",
        )
    return UploadKind(
        "unsupported", extension,
        reason=f"'{extension}' is not a supported format. Supported: {_SUPPORTED_LIST}.",
    )


def supported_extensions() -> tuple[str, ...]:
    """Every extension the system accepts, for the file picker's filter."""
    return tuple(sorted(CATALOGUE_FORMATS) + sorted(DOCUMENT_FORMATS))
