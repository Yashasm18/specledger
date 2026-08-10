ALTER TABLE document_assets
    ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'generic';
