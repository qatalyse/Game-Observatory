-- M1A / 001: Namespace, identity, and collection-run foundation.
-- Application schemas are NOT exposed by Supabase Data API configuration.
-- Execute under the migration owner (postgres) in a controlled environment.
BEGIN;

CREATE SCHEMA core;
CREATE SCHEMA raw;
CREATE SCHEMA ops;
CREATE SCHEMA analytics;

REVOKE ALL ON SCHEMA core, raw, ops, analytics FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA core, raw, ops, analytics
  REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA core, raw, ops, analytics
  REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA core, raw, ops, analytics
  REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;

CREATE TABLE core.countries (
    country_code char(2) PRIMARY KEY,
    country_name text NOT NULL,
    region text NOT NULL,
    CONSTRAINT country_uppercase CHECK (country_code = upper(country_code))
);

CREATE TABLE core.games (
    game_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_title text NOT NULL CHECK (length(btrim(canonical_title)) > 0),
    publisher text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Distinct external app IDs belong to a platform; presence in markets is separate.
-- game_id is intentionally nullable until a human-verified canonical mapping exists.
CREATE TABLE core.store_listings (
    listing_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id bigint REFERENCES core.games(game_id) ON DELETE RESTRICT,
    platform text NOT NULL CHECK (platform IN ('steam', 'apple')),
    external_app_id text NOT NULL CHECK (length(btrim(external_app_id)) > 0),
    display_title text NOT NULL CHECK (length(btrim(display_title)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (platform, external_app_id),
    UNIQUE (listing_id, platform)
);

CREATE TABLE core.listing_markets (
    listing_id bigint NOT NULL REFERENCES core.store_listings(listing_id) ON DELETE RESTRICT,
    country_code char(2) NOT NULL REFERENCES core.countries(country_code),
    PRIMARY KEY (listing_id, country_code)
);

-- Each run targets one source request / market / app, not an entire scheduler batch.
CREATE TABLE ops.collection_runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source text NOT NULL CHECK (source IN ('apple', 'steam')),
    dataset text NOT NULL CHECK (length(btrim(dataset)) > 0),
    request_scope jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(request_scope) = 'object'),
    idempotency_key text UNIQUE,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'partial', 'failed', 'unsupported')),
    http_status integer CHECK (http_status BETWEEN 100 AND 599),
    records_fetched integer NOT NULL DEFAULT 0 CHECK (records_fetched >= 0),
    records_written integer NOT NULL DEFAULT 0 CHECK (records_written >= 0),
    error_code text,
    error_message text,
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK ((status = 'running' AND finished_at IS NULL)
       OR (status <> 'running' AND finished_at IS NOT NULL))
);

INSERT INTO core.countries (country_code, country_name, region) VALUES
 ('SG','Singapore','SEA'),('JP','Japan','East Asia'),
 ('US','United States','North America'),('KR','South Korea','East Asia'),
 ('CN','China','East Asia'),('MY','Malaysia','SEA'),
 ('TH','Thailand','SEA'),('ID','Indonesia','SEA'),
 ('PH','Philippines','SEA'),('VN','Vietnam','SEA');

REVOKE ALL ON ALL TABLES IN SCHEMA core, raw, ops, analytics FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA core, raw, ops, analytics FROM PUBLIC, anon, authenticated;
COMMIT;
