ALTER TABLE extraction_artifacts
    ADD COLUMN IF NOT EXISTS review_state TEXT NOT NULL DEFAULT 'pending_review'
    CHECK (review_state IN ('pending_review', 'approved', 'rejected'));

CREATE INDEX IF NOT EXISTS idx_extraction_artifacts_review_state
    ON extraction_artifacts (organization_id, review_state, created_at DESC);
