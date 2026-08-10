CREATE TABLE IF NOT EXISTS extraction_artifacts (
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    artifact_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    object_key TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'extraction.v1',
    fact_count INTEGER NOT NULL DEFAULT 0 CHECK (fact_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, artifact_id),
    FOREIGN KEY (organization_id, document_id)
        REFERENCES document_assets(organization_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_extraction_artifacts_document
    ON extraction_artifacts (organization_id, document_id, created_at DESC);
