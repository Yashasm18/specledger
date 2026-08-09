# PostgreSQL deployment path

SpecLedger's production storage path is PostgreSQL. SQLite remains the local adapter used for fast tests and offline development.

## Required environment

```bash
DATABASE_URL=postgresql://user:password@host:5432/specledger
```

## Install production database support

```bash
pip install -r requirements.txt -r requirements-postgres.txt
```

## Initialize the adapter

```python
from backend.specledger.postgres_repository import PostgresRepository

repository = PostgresRepository()
```

## Why PostgreSQL

- transactional writes for catalogue updates;
- JSONB for flexible industrial attributes;
- composite tenant keys for organization isolation;
- indexes for SKU, category, and update-time queries;
- connection pooling for concurrent API workers;
- a clear path to read replicas and partitioning;
- referential integrity between products, versions, attributes, and evidence.

The adapter is intentionally optional in local development. No credentials or live database access belong in the repository.

