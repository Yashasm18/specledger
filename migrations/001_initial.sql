CREATE TABLE IF NOT EXISTS organizations (
    organization_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO organizations (organization_id, name)
VALUES ('default', 'Local Development Organization')
ON CONFLICT (organization_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS products (
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    product_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, product_id),
    UNIQUE (organization_id, sku)
);

CREATE TABLE IF NOT EXISTS product_versions (
    organization_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (organization_id, version_id),
    FOREIGN KEY (organization_id, product_id)
      REFERENCES products(organization_id, product_id)
);

CREATE TABLE IF NOT EXISTS attributes (
    organization_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value JSONB NOT NULL,
    unit TEXT,
    status TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    PRIMARY KEY (organization_id, version_id, name),
    FOREIGN KEY (organization_id, version_id)
      REFERENCES product_versions(organization_id, version_id)
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id BIGSERIAL PRIMARY KEY,
    organization_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    attribute_name TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    page INTEGER,
    locator TEXT,
    excerpt TEXT,
    captured_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (organization_id, version_id, attribute_name)
      REFERENCES attributes(organization_id, version_id, name)
);

CREATE TABLE IF NOT EXISTS import_jobs (
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    job_id TEXT NOT NULL,
    state TEXT NOT NULL,
    total_items INTEGER NOT NULL,
    completed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    review_items INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, job_id)
);

CREATE TABLE IF NOT EXISTS import_items (
    organization_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    item_number INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    state TEXT NOT NULL,
    error_message TEXT,
    PRIMARY KEY (organization_id, job_id, item_number),
    FOREIGN KEY (organization_id, job_id)
      REFERENCES import_jobs(organization_id, job_id)
);

CREATE TABLE IF NOT EXISTS processed_fingerprints (
    organization_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    product_id TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id BIGSERIAL PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    actor_id TEXT,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS products_category_idx ON products (organization_id, category);
CREATE INDEX IF NOT EXISTS products_updated_idx ON products (organization_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS versions_product_idx ON product_versions (organization_id, product_id, created_at DESC);
CREATE INDEX IF NOT EXISTS jobs_state_idx ON import_jobs (organization_id, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS audit_entity_idx ON audit_events (organization_id, entity_type, entity_id, created_at DESC);

