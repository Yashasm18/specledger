-- Persist the optional LLM tier's output.
--
-- Without these columns, PostgresCatalogueStore writes only the fields it
-- knows about and silently drops llm_usage/llm_suggestion — so the tier ran,
-- was billed, and its results vanished on save. The in-memory dev store keeps
-- the whole batch dict, which is why this only reproduced against Postgres.
--
-- Both are nullable: a batch ingested without ai_assist has no LLM output,
-- and that is the normal case.

ALTER TABLE catalogue_batches
    ADD COLUMN IF NOT EXISTS llm_usage JSONB;

ALTER TABLE catalogue_rows
    ADD COLUMN IF NOT EXISTS llm_suggestion JSONB;

COMMENT ON COLUMN catalogue_batches.llm_usage IS
    'Token counts, call count and derived cost for the LLM tier on this batch. Null when the tier did not run.';

COMMENT ON COLUMN catalogue_rows.llm_suggestion IS
    'AI-inferred classification for a row the deterministic classifier left generic: classpath, confidence, prompt version. Advisory only — never auto-approves.';
