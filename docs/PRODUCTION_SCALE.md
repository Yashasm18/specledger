# Production-scale direction

SpecLedger is developed locally with SQLite, but SQLite is not the target production database. The domain and service layers must remain independent of the storage engine so the local adapter can be replaced by PostgreSQL without changing product logic.

## Target deployment topology

```text
Web dashboard / partner API
              |
        API gateway
              |
      Stateless API services
       /        |         \
 PostgreSQL  Object store  Queue
  records    PDFs/images   jobs
       \        |         /
       Processing workers
              |
      Search and impact indexes
```

## Responsibilities

### PostgreSQL

The source of truth for organizations, users, products, versions, attributes, evidence metadata, imports, reviews, and audit events.

Production requirements:

- tenant-aware keys and row-level authorization;
- indexed SKU, manufacturer, category, status, and updated-at queries;
- append-only version history;
- transactions for catalogue updates;
- migrations managed in source control;
- read replicas for heavy catalogue browsing when needed.

### Object storage

Original PDFs, images, spreadsheets, and extracted artifacts belong in object storage, not PostgreSQL rows. PostgreSQL stores object keys, hashes, metadata, and access policy.

### Queue and workers

Document parsing, AI enrichment, validation, and impact analysis are asynchronous jobs. Workers must be independently scalable and retryable. One bad product must not stop an import containing thousands or millions of records.

### Search and impact indexes

Catalogue search and relationship traversal are read-optimized projections. They can be rebuilt from PostgreSQL and must not become the only copy of product truth.

## Required large-scale properties

- batch imports rather than one-record-only workflows;
- idempotency keys and content hashes;
- resumable jobs with per-record status;
- back-pressure and rate limits;
- pagination and streaming exports;
- dead-letter handling for permanently failed records;
- audit logs for every accepted or rejected change;
- organization-level isolation;
- observability for latency, throughput, failures, and review backlog;
- schema versioning for changing industrial taxonomies.

## Local-to-production rule

The local SQLite adapter exists for fast development and tests. It must implement the same repository contract as the PostgreSQL adapter. No product behavior may depend on SQLite-specific SQL.

## Scale claims

The prototype will demonstrate the architecture using a small public/synthetic dataset. We will not claim production throughput until it is measured. Scale will be demonstrated through batch jobs, independent record processing, pagination, idempotency, and failure recovery—not by pretending that a small test dataset is a production benchmark.

