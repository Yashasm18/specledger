-- Arrivals at the live dashboard.
--
-- Deliberately holds no identifier: no IP address, no cookie, no session
-- token that outlives the page. A timestamp, the referring link and a
-- summarised browser are enough to know that someone opened the app and
-- where they came from, and are not personal data.

CREATE TABLE IF NOT EXISTS site_visits (
    visit_id     BIGSERIAL PRIMARY KEY,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    referrer     TEXT NOT NULL DEFAULT '',
    browser      TEXT NOT NULL DEFAULT '',
    path         TEXT NOT NULL DEFAULT '',
    workspace    TEXT NOT NULL DEFAULT '',
    is_bot       BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS site_visits_time_idx ON site_visits (occurred_at DESC);

COMMENT ON TABLE site_visits IS
    'One row per arrival at the dashboard. No IP address or identifier is stored.';
COMMENT ON COLUMN site_visits.browser IS
    'Summarised user agent (e.g. "Chrome on macOS"), not the raw string.';
COMMENT ON COLUMN site_visits.is_bot IS
    'True when the user agent identifies a crawler. Bot traffic is the main source of noise on a public page.';
