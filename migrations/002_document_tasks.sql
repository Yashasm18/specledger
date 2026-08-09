CREATE TABLE IF NOT EXISTS document_assets (
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    document_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    object_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    status TEXT NOT NULL DEFAULT 'registered',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, document_id),
    UNIQUE (organization_id, content_hash)
);

CREATE TABLE IF NOT EXISTS processing_tasks (
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    task_id TEXT NOT NULL,
    document_id TEXT,
    task_type TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_by TEXT,
    locked_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, task_id),
    FOREIGN KEY (organization_id, document_id)
      REFERENCES document_assets(organization_id, document_id)
);

CREATE INDEX IF NOT EXISTS document_hash_idx ON document_assets (organization_id, content_hash);
CREATE INDEX IF NOT EXISTS task_claim_idx ON processing_tasks (state, available_at, created_at);

