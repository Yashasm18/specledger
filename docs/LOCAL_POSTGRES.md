# Local PostgreSQL workflow

PostgreSQL is now the required database for the product architecture. SQLite is not used by the production application path.

## Start the database

```bash
docker compose up -d postgres
```

The database is available at:

```text
postgresql://specledger:specledger_dev_only@localhost:5432/specledger
```

The migration in `migrations/001_initial.sql` runs automatically when the volume is created.

## Stop the database

```bash
docker compose stop postgres
```

The named Docker volume preserves data between stops. Do not delete the volume unless you intentionally want to destroy the local database.

## Production

Use a managed PostgreSQL service and provide `DATABASE_URL` through a secret manager. Never commit a production connection string.

