-- M1A / 002: Apple chart snapshots and app metadata.
BEGIN;
CREATE TABLE raw.apple_chart_snapshots (
    snapshot_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL UNIQUE REFERENCES ops.collection_runs(run_id),
    country_code char(2) NOT NULL REFERENCES core.countries(country_code),
    chart_type text NOT NULL CHECK (chart_type IN ('free', 'paid', 'grossing')),
    category_code text NOT NULL CHECK (length(btrim(category_code)) > 0),
    observed_at timestamptz NOT NULL,
    collected_at timestamptz NOT NULL DEFAULT now(),
    source_updated_at timestamptz,
    status text NOT NULL CHECK (status IN ('complete', 'partial')),
    requested_depth integer NOT NULL CHECK (requested_depth BETWEEN 1 AND 200),
    entry_count integer NOT NULL CHECK (entry_count BETWEEN 1 AND 200),
    CHECK (entry_count <= requested_depth),
    UNIQUE (country_code, chart_type, category_code, observed_at)
);

CREATE TABLE raw.apple_chart_entries (
    snapshot_id uuid NOT NULL REFERENCES raw.apple_chart_snapshots(snapshot_id) ON DELETE RESTRICT,
    listing_id bigint NOT NULL REFERENCES core.store_listings(listing_id) ON DELETE RESTRICT,
    rank integer NOT NULL CHECK (rank > 0),
    PRIMARY KEY (snapshot_id, rank),
    UNIQUE (snapshot_id, listing_id)
);

CREATE TABLE raw.apple_app_metadata_snapshots (
    metadata_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES ops.collection_runs(run_id),
    listing_id bigint NOT NULL REFERENCES core.store_listings(listing_id),
    country_code char(2) NOT NULL REFERENCES core.countries(country_code),
    observed_at timestamptz NOT NULL,
    version text,
    rating_average numeric(4,2) CHECK (rating_average BETWEEN 0 AND 5),
    rating_count bigint CHECK (rating_count >= 0),
    price_amount numeric(12,2) CHECK (price_amount >= 0),
    currency_code char(3),
    UNIQUE (listing_id, country_code, observed_at)
);

CREATE INDEX apple_snapshots_market_time_idx
 ON raw.apple_chart_snapshots (country_code, chart_type, category_code, observed_at DESC);
CREATE INDEX apple_entries_listing_idx ON raw.apple_chart_entries (listing_id, snapshot_id);
CREATE INDEX apple_metadata_listing_time_idx
 ON raw.apple_app_metadata_snapshots (listing_id, country_code, observed_at DESC);

-- Structural source-consistency rules (platform and country eligibility) require
-- collector validation or dedicated database triggers; see docs/DATABASE.md.
REVOKE ALL ON ALL TABLES IN SCHEMA raw FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA raw FROM PUBLIC, anon, authenticated;
COMMIT;
