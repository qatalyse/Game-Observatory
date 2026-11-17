-- Run with psql -X -v ON_ERROR_STOP=1 -f supabase/tests/001_schema_smoke.sql
-- This test deliberately rolls back ALL fixture inserts.
BEGIN;
DO $$
DECLARE
    v_game bigint;
    v_apple bigint;
    v_steam bigint;
    v_achievement bigint;
    v_apple_run uuid;
    v_steam_run uuid;
    v_snapshot uuid;
    v_count bigint;
BEGIN
    IF (SELECT count(*) FROM core.countries) < 10 THEN
        RAISE EXCEPTION 'Expected 10 seeded markets';
    END IF;

    INSERT INTO core.games (canonical_title) VALUES ('M1A fixture game')
      RETURNING game_id INTO v_game;
    INSERT INTO core.store_listings (game_id, platform, external_app_id, display_title)
      VALUES (v_game, 'apple', 'm1a-test-apple', 'M1A Fixture Apple')
      RETURNING listing_id INTO v_apple;
    INSERT INTO core.store_listings (game_id, platform, external_app_id, display_title)
      VALUES (v_game, 'steam', 'm1a-test-steam', 'M1A Fixture Steam')
      RETURNING listing_id INTO v_steam;
    INSERT INTO core.listing_markets (listing_id, country_code) VALUES (v_apple, 'SG');

    INSERT INTO ops.collection_runs (source, dataset, idempotency_key, finished_at, status)
      VALUES ('apple', 'chart', 'm1a-fixture-apple', now(), 'succeeded')
      RETURNING run_id INTO v_apple_run;
    INSERT INTO ops.collection_runs (source, dataset, idempotency_key, finished_at, status)
      VALUES ('steam', 'players', 'm1a-fixture-steam', now(), 'succeeded')
      RETURNING run_id INTO v_steam_run;

    INSERT INTO raw.apple_chart_snapshots
      (run_id, country_code, chart_type, category_code, observed_at,
       status, requested_depth, entry_count)
      VALUES (v_apple_run, 'SG', 'free', 'games', now(), 'complete', 100, 1)
      RETURNING snapshot_id INTO v_snapshot;
    INSERT INTO raw.apple_chart_entries (snapshot_id, listing_id, rank)
      VALUES (v_snapshot, v_apple, 1);

    INSERT INTO raw.steam_player_snapshots
      (listing_id, run_id, observed_at, player_count)
      VALUES (v_steam, v_steam_run, now(), 42);

    INSERT INTO core.steam_achievements (listing_id, source_achievement_id)
      VALUES (v_steam, 'm1a-achievement')
      RETURNING achievement_id INTO v_achievement;
    INSERT INTO raw.steam_achievement_snapshots
      (achievement_id, run_id, observed_at, completion_pct)
      VALUES (v_achievement, v_steam_run, now(), 23.5000);

    INSERT INTO raw.steam_reviews
      (review_id, listing_id, created_at, source_updated_at, last_seen_at, recommended)
      VALUES ('m1a-review', v_steam, now(), now(), now(), true);

    SELECT count(*) INTO v_count FROM analytics.apple_rank_history
      WHERE listing_id = v_apple;
    IF v_count <> 1 THEN RAISE EXCEPTION 'Apple analytics expected one record'; END IF;
    SELECT count(*) INTO v_count FROM analytics.steam_daily_players
      WHERE listing_id = v_steam;
    IF v_count <> 1 THEN RAISE EXCEPTION 'Steam analytics expected one record'; END IF;

    BEGIN
      INSERT INTO raw.apple_chart_entries (snapshot_id, listing_id, rank)
        VALUES (v_snapshot, v_steam, 1);
      RAISE EXCEPTION 'Duplicate rank unexpectedly accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;

    BEGIN
      INSERT INTO raw.steam_player_snapshots
        (listing_id, run_id, observed_at, player_count)
        VALUES (v_steam, v_steam_run, now() + interval '1 second', -5);
      RAISE EXCEPTION 'Negative player count unexpectedly accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    IF has_schema_privilege('anon', 'raw', 'USAGE')
      OR has_schema_privilege('authenticated', 'raw', 'USAGE')
      OR has_schema_privilege('anon', 'analytics', 'USAGE') THEN
       RAISE EXCEPTION 'Client role unexpectedly has application schema access';
    END IF;
    RAISE NOTICE 'M1A relational smoke tests passed';
END $$;
ROLLBACK;
