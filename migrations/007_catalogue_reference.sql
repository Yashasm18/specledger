-- Reference data and catalogue batch persistence
-- Adds tables for canonical reference data, ingested catalogue batches,
-- catalogue rows with enrichment results, and evaluation runs.

-- Canonical manufacturer reference
CREATE TABLE IF NOT EXISTS reference_manufacturers (
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    canonical_name TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT NOT NULL DEFAULT 'seed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, canonical_name)
);

-- Canonical brand reference
CREATE TABLE IF NOT EXISTS reference_brands (
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    canonical_name TEXT NOT NULL,
    manufacturer_canonical TEXT,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT NOT NULL DEFAULT 'seed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, canonical_name)
);

-- UOM reference (shared across organizations)
CREATE TABLE IF NOT EXISTS reference_uom (
    canonical_unit TEXT NOT NULL PRIMARY KEY,
    dimension TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb
);

-- Catalogue batch metadata
CREATE TABLE IF NOT EXISTS catalogue_batches (
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    column_list JSONB NOT NULL DEFAULT '[]'::jsonb,
    row_count INTEGER NOT NULL DEFAULT 0,
    verified_rate DOUBLE PRECISION,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, batch_id)
);

-- Individual catalogue rows with raw and enriched values
CREATE TABLE IF NOT EXISTS catalogue_rows (
    organization_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    source_fingerprint TEXT NOT NULL,
    raw_values JSONB NOT NULL DEFAULT '{}'::jsonb,
    enriched_values JSONB NOT NULL DEFAULT '{}'::jsonb,
    overall_status TEXT NOT NULL DEFAULT 'review_required',
    overall_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    review_state TEXT NOT NULL DEFAULT 'pending_review',
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    PRIMARY KEY (organization_id, batch_id, row_number),
    FOREIGN KEY (organization_id, batch_id)
      REFERENCES catalogue_batches(organization_id, batch_id)
);

-- Evaluation run results
CREATE TABLE IF NOT EXISTS evaluation_runs (
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    run_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    ground_truth_file TEXT NOT NULL,
    ground_truth_rows INTEGER NOT NULL DEFAULT 0,
    matched_rows INTEGER NOT NULL DEFAULT 0,
    overall_exact_accuracy DOUBLE PRECISION,
    overall_normalized_accuracy DOUBLE PRECISION,
    complete_row_accuracy DOUBLE PRECISION,
    average_row_accuracy DOUBLE PRECISION,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, run_id),
    FOREIGN KEY (organization_id, batch_id)
      REFERENCES catalogue_batches(organization_id, batch_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS catalogue_batches_org_idx
    ON catalogue_batches (organization_id, ingested_at DESC);
CREATE INDEX IF NOT EXISTS catalogue_rows_status_idx
    ON catalogue_rows (organization_id, batch_id, overall_status);
CREATE INDEX IF NOT EXISTS catalogue_rows_review_idx
    ON catalogue_rows (organization_id, review_state)
    WHERE review_state = 'pending_review';
CREATE INDEX IF NOT EXISTS evaluation_runs_batch_idx
    ON evaluation_runs (organization_id, batch_id, created_at DESC);
