# SpecLedger

SpecLedger is an evidence-backed industrial product intelligence system.

It transforms fragmented product information into structured, enriched, validated, versioned catalogue records and shows what changes affect before corrected data is published.

## Project goal

The first working workflow will be:

```text
Upload product documents
    -> Extract structured attributes
    -> Compare product versions
    -> Detect conflicts and changes
    -> Show source evidence
    -> Identify affected catalogue records
    -> Approve and export corrected data
```

## Initial technology choices

- Python 3.11+ for the backend and data-processing pipeline
- FastAPI for HTTP APIs
- Pydantic for typed product records and validation
- SQLite for the first local database
- PyMuPDF for PDF text extraction
- React + TypeScript for the dashboard, added after the backend workflow is stable
- pytest for automated tests

We will add an LLM only after deterministic extraction, validation, provenance, and version comparison work reliably. The system must remain useful and testable without an AI API.

## Development principles

- Build one verified milestone at a time.
- Keep source evidence attached to extracted values.
- Never silently overwrite conflicting product data.
- Treat inferred values as suggestions requiring review.
- Use public or synthetic data for the hackathon prototype.
- Keep secrets out of the repository.

## Current status

The project foundation is being created. The next implementation milestone is a small backend that accepts a product record, validates it, stores its source evidence, and compares two versions.

