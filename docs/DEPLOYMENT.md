# Production deployment

The public application requires two deployments:

1. the React/Vite frontend on Vercel;
2. the FastAPI service with PostgreSQL on a container host.

The frontend must never run production catalogue operations without the API.

## Backend

The repository includes `Dockerfile` and `render.yaml`. On Render, create a
Blueprint from the repository. Render provisions the API and PostgreSQL, then
checks `GET /health`.

Required backend environment variables:

```text
DATABASE_URL=<managed PostgreSQL connection string>
ENVIRONMENT=production
CORS_ORIGINS=https://specledger-app.vercel.app
SPECLEDGER_OBJECT_STORE=/tmp/specledger-object-data
```

The local object store is acceptable for a short-lived hackathon demo. A durable
production deployment must replace it with S3-compatible object storage.

## Frontend

After the backend is live, configure this Vercel project variable and redeploy:

```text
VITE_API_URL=https://<your-api-host>
```

Verify these requests from the deployed browser application:

- `GET <VITE_API_URL>/health` returns `200`;
- `GET <VITE_API_URL>/catalogue/batches` returns JSON;
- spreadsheet ingestion creates a batch;
- review decisions persist after refresh;
- exports are returned by the API.

If the API is missing or unavailable, SpecLedger reports the failure. It does
not generate substitute product specifications, evidence, approvals or exports.
