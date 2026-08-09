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

The next worker milestone will persist extracted artifacts and feed them into the structured-attribute extraction pipeline.

