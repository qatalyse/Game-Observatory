-- M1A / 003: Steam concurrent players, achievements and current reviews.
BEGIN;
CREATE TABLE core.steam_achievements (
    achievement_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id bigint NOT NULL REFERENCES core.store_listings(listing_id),
    source_achievement_id text NOT NULL CHECK (length(btrim(source_achievement_id)) > 0),
    display_name text,
    UNIQUE (listing_id, source_achievement_id)
);

CREATE TABLE raw.steam_player_snapshots (
    player_snapshot_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id bigint NOT NULL REFERENCES core.store_listings(listing_id),
    run_id uuid NOT NULL UNIQUE REFERENCES ops.collection_runs(run_id),
    observed_at timestamptz NOT NULL,
    player_count bigint NOT NULL CHECK (player_count >= 0),
    UNIQUE (listing_id, observed_at)
);

CREATE TABLE raw.steam_achievement_snapshots (
    achievement_id bigint NOT NULL REFERENCES core.steam_achievements(achievement_id),
    run_id uuid NOT NULL REFERENCES ops.collection_runs(run_id),
    observed_at timestamptz NOT NULL,
    completion_pct numeric(7,4) NOT NULL CHECK (completion_pct BETWEEN 0 AND 100),
    PRIMARY KEY (achievement_id, observed_at)
);

-- Reviews are mutable source records; preserve latest observed state.
CREATE TABLE raw.steam_reviews (
    review_id text PRIMARY KEY CHECK (length(btrim(review_id)) > 0),
    listing_id bigint NOT NULL REFERENCES core.store_listings(listing_id),
    created_at timestamptz NOT NULL,
    source_updated_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    recommended boolean NOT NULL,
    language text,
    playtime_minutes integer CHECK (playtime_minutes >= 0),
    review_text text,
    developer_response text,
    last_run_id uuid REFERENCES ops.collection_runs(run_id),
    CHECK (source_updated_at >= created_at)
);

CREATE INDEX steam_players_listing_time_idx
 ON raw.steam_player_snapshots (listing_id, observed_at DESC);
CREATE INDEX steam_achievements_time_idx
 ON raw.steam_achievement_snapshots (achievement_id, observed_at DESC);
CREATE INDEX steam_reviews_listing_created_idx
 ON raw.steam_reviews (listing_id, created_at DESC);
CREATE INDEX steam_reviews_last_seen_idx ON raw.steam_reviews (last_seen_at DESC);

REVOKE ALL ON ALL TABLES IN SCHEMA core, raw FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA core, raw FROM PUBLIC, anon, authenticated;
COMMIT;
