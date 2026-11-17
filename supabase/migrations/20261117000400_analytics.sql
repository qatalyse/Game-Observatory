-- M1A / 004: Read-only relational analytics starting points.
-- Views are security_invoker to avoid silently bypassing caller privileges/RLS.
BEGIN;

CREATE VIEW analytics.apple_rank_history WITH (security_invoker = true) AS
 SELECT
    e.listing_id, s.country_code, s.chart_type, s.category_code,
    s.snapshot_id, s.observed_at, s.collected_at, s.status,
    e.rank, l.display_title,
    LAG(e.rank) OVER (
        PARTITION BY e.listing_id, s.country_code, s.chart_type, s.category_code
        ORDER BY s.observed_at, s.snapshot_id
    ) AS previous_observed_rank,
    LAG(s.observed_at) OVER (
        PARTITION BY e.listing_id, s.country_code, s.chart_type, s.category_code
        ORDER BY s.observed_at, s.snapshot_id
    ) AS previous_seen_at
 FROM raw.apple_chart_entries e
 JOIN raw.apple_chart_snapshots s USING (snapshot_id)
 JOIN core.store_listings l USING (listing_id);

CREATE VIEW analytics.steam_daily_players WITH (security_invoker = true) AS
 SELECT listing_id,
        (observed_at AT TIME ZONE 'UTC')::date AS day_utc,
        count(*)::integer AS samples,
        round(avg(player_count), 2) AS average_sampled_players,
        max(player_count) AS highest_sampled_players,
        min(player_count) AS lowest_sampled_players
 FROM raw.steam_player_snapshots
 GROUP BY listing_id, (observed_at AT TIME ZONE 'UTC')::date;

CREATE VIEW analytics.steam_daily_reviews WITH (security_invoker = true) AS
 SELECT listing_id,
        (created_at AT TIME ZONE 'UTC')::date AS day_utc,
        count(*)::integer AS reviews_observed,
        count(*) FILTER (WHERE recommended)::integer AS recommended_reviews,
        round(100.0 * count(*) FILTER (WHERE recommended) / NULLIF(count(*), 0), 2)
            AS recommended_pct
 FROM raw.steam_reviews
 GROUP BY listing_id, (created_at AT TIME ZONE 'UTC')::date;

CREATE VIEW analytics.steam_achievement_trends WITH (security_invoker = true) AS
 SELECT a.listing_id, s.achievement_id, s.observed_at, s.completion_pct,
    LAG(s.completion_pct) OVER (
       PARTITION BY s.achievement_id ORDER BY s.observed_at
    ) AS previous_completion_pct
 FROM raw.steam_achievement_snapshots s
 JOIN core.steam_achievements a USING (achievement_id);

REVOKE ALL ON ALL TABLES IN SCHEMA analytics FROM PUBLIC, anon, authenticated;
COMMIT;
