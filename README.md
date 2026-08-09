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

The first backend domain milestone is complete. The project now has typed product, attribute, evidence, and version models; deterministic validation; version comparison; synthetic sample data; and automated tests.

The persistence milestone is complete. Product records, versions, attributes, and source evidence can now be stored in SQLite and loaded again. The application service can validate stored products and compare their latest versions.

The HTTP API and first document-ingestion endpoint are now implemented. The API supports product creation, retrieval, validation, version comparison, and PDF text extraction with page-level source references.

The production-scale target is documented in [docs/PRODUCTION_SCALE.md](docs/PRODUCTION_SCALE.md). SQLite is only the local development adapter; the target architecture uses PostgreSQL, object storage, asynchronous workers, and read-optimized search/impact indexes.

To run the API after installing `requirements.txt`:

```bash
uvicorn backend.specledger.http_api:app --reload
```
