ALTER TABLE extraction_artifacts
    ADD COLUMN IF NOT EXISTS review_actor_id TEXT,
    ADD COLUMN IF NOT EXISTS review_comment TEXT;
