# Document worker milestone

The document worker is the first asynchronous processing component in SpecLedger.

## What it does

1. Claims a `pdf_extract` task from PostgreSQL.
2. Loads the document through an object-store interface.
3. Extracts text page by page.
4. Marks the task `completed` when successful.
5. Marks the task `failed` with an error when processing fails.

## Why this is scalable

The API does not perform the long-running extraction work. Multiple worker processes can claim tasks concurrently using PostgreSQL row locking. The local file store is only a development adapter; the same interface can be backed by S3, GCS, or Azure Blob Storage.

## What it produces

Each completed task stores an artifact holding the document's pages, the typed facts extracted from them, and a validation report. A fact carries the page number and the surrounding sentence, so a reviewer can check any claim against the document rather than trusting the extractor.

Extraction reads PDF, TXT, DOCX and RTF. A specification must be a labelled value occupying the remainder of its line; a document with no labelled specification returns none rather than a guess. That rule exists because real manufacturer PDFs, unlike the label-value fixtures in the test suite, are prose — and two of them produced fabricated values before it was added.

## Reaching the catalogue

`GET /documents/for-part/{part_number}` returns the documents naming a part and what each says about it, matched exactly on the part number. The row inspector shows them against the record. These are proposals for a reviewer: writing an accepted value into the delivered 252 columns is not yet wired, because the attribute slots are per-category schema-driven and adding an attribute to a row's values changes nothing in the export. That write-back is the remaining milestone.

