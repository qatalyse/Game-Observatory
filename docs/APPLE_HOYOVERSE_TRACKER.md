# Manual HoYoverse Apple Top Grossing tracker

This additional exporter leaves the diagnostic collector and full-chart Adventure
exporter unchanged. Open **Actions → Export HoYoverse Apple targeted rankings →
Run workflow**, select the branch containing this workflow, then download both
artifacts from the completed run. GitHub requires a newly added manual workflow
to exist on the default branch before its Run workflow button becomes available.
The collection trigger is `workflow_dispatch` only.

The dedicated [roster config](../collector/game_observatory/apple_hoyoverse.json)
controls genres, stable game IDs, default listing IDs, market overrides and depth.
Markets remain SG, US, JP, KR, CN, MY, TH, ID, PH and VN. Genres are checked
against existing `apple.GENRES`: Adventure (7002) targets Genshin and Star Rail;
Role-Playing (7014) targets those two plus Zenless Zone Zero.

## Regional listings (roster version focused-three-titles-v3)

A game can have different Apple listings by market. The first version searched
global IDs everywhere, which missed regional releases. The corrected mapping is:

| Game | Default listing | CN | VN | Other overrides |
| --- | --- | --- | --- | --- |
| Genshin Impact | 1517783697 | 1467190251 | 6451477469 | — |
| Honkai: Star Rail | 1599719154 | 1523037824 | 6451473600 | — |
| Zenless Zone Zero | 1606356401 | 1606359076 | 6476137851 | — |

Each override has an Apple listing reference in `market_mapping_sources`.
Examples: [CN Star Rail](https://apps.apple.com/cn/app/id1523037824),
[CN Genshin](https://apps.apple.com/cn/app/id1467190251),
[VN Star Rail](https://apps.apple.com/vn/app/honkai-star-rail-3t-online/id6451473600),
[VN Genshin](https://apps.apple.com/vn/app/genshin-impact-funtap/id6451477469),
and [VN ZZZ](https://apps.apple.com/vn/app/zenless-zone-zero-gamota/id6476137851).

`market_app_ids` overrides the default ID for that country. An explicit JSON
`null` means unresolved: **do not fall back to the global ID**. This remains
supported for custom rosters even though all current default targets have
configured listing IDs. An unresolved mapping is not proof of unavailability.
Missing override keys retain the configured default. Custom legacy rosters with
only `app_id` and `title` remain supported.

`game_id` is the stable identity for cross-market analysis; `app_id` is the
actual market listing searched, blank when unresolved. `canonical_app_id`
retains the original default ID to help join earlier exports. Do not group
regional listings solely by `app_id`. Duplicate market IDs within a genre and
inconsistent mappings for the same game across genres are rejected.

The focused default roster excludes Honkai Impact 3rd and Tears of Themis at
the user's request. Apple category labels differ across markets: Honkai shows
[Action in the US](https://apps.apple.com/us/app/honkai-impact-3rd/id1336342304)
and [Role-Playing in Japan](https://apps.apple.com/jp/app/崩壊3rd/id1172809651);
Tears of Themis shows
[Role-Playing in the US](https://apps.apple.com/us/app/tears-of-themis/id1517957388)
and [Card in China](https://apps.apple.com/cn/app/未定事件簿/id1507310279).
Category labels and page badges are not substituted for Top Grossing feed
membership or rank. The two removed titles can be revisited in a custom roster.

The previous regional roster (v2) included those titles and used an explicit
unresolved VN Tears of Themis mapping. That is historical context, not a current
default target. Old artifacts and any existing sheet history are left unchanged.
Fresh collections use the v3 roster version; the Sheets validator rejects CSVs
whose roster version or target set differs from the active config.

**Earlier exports:** CN/VN rows and Honkai regional rows from roster v1 do not
establish that the games were outside the charts. Exclude those affected rows
from rank-history conclusions and make a fresh manual collection after the fix.
Old artifacts are left untouched. Reported ranks are offline regression
fixtures only; they are never inserted as live observations or backfilled.

Apple's legacy RSS endpoint has no App-ID filter. The tracker fetches each
market/genre Top Grossing chart once at limit=100, then matches exact App IDs
locally, preserving the original feed positions. There are **20 chart requests**
and **50 game records** with the default config. No per-game lookup requests,
retries, reduced-depth fallback, or title-based matching are used. Legacy
endpoints can fail or return fewer entries; depth 100 is requested, not promised.

## CSV artifacts and status rules

Artifacts are retained for 30 days and include the GitHub run ID and attempt
in their names:

- `apple-hoyoverse-rankings-<run>-<attempt>`: `apple_hoyoverse_rankings.csv`,
  one record per configured game/market/genre/run, even on failure.
- `apple-hoyoverse-chart-statuses-<run>-<attempt>`:
  `apple_hoyoverse_chart_statuses.csv`, one record per chart attempt.

Shared columns: `run_id, snapshot_id, retrieved_at_utc, country, store,
feed_type, genre, genre_id, requested_depth, coverage_depth, chart_status,
http_status, error, source, source_url, feed_updated_at, feed_fields, entry_fields,
roster_version`.

Game columns: `app_id, title, observed_title, rank, status, store_url, game_id,
canonical_app_id, mapping_status, mapping_source_url, mapping_note, status_reason`.
`title` is configured; `observed_title` and `store_url` come from the feed.
Unobserved ranks are blank CSV cells (null), never 101.

Chart-only columns: `source_count, chart_complete, unresolved_game_ids`.
`mapping_status` is `default`, `market-override` or `unresolved`. The mapping
reference and note explain the selected listing independently of feed metadata.
Chart completeness does not imply listing coverage: an unresolved listing is
`unknown` with reason `unresolved_market_listing`, even on a complete chart.
Retrieval/validation errors remain `error` regardless of mapping state. Join files on `snapshot_id`;
`run_id` groups all charts. Each chart gets a unique snapshot ID.
GitHub run IDs include attempt; standalone invocations use a new UUID.
`retrieved_at_utc` records request/attempt completion time in UTC;
`feed_updated_at` is separate source metadata.

| Chart status | Meaning | Absent game status |
| --- | --- | --- |
| complete | HTTP success and exactly the requested number of valid, unique entries | outside-chart if listing resolved; otherwise unknown |
| partial | Valid nonempty response shorter than requested | unknown |
| empty | Valid feed with zero entries or no entry field | unknown |
| error | HTTP, transport, JSON or entry validation failure | error |

An observed game is `ranked`, including on a partial chart; its
`chart_status` still preserves partial coverage. `outside-chart` only means
the resolved market listing is absent from this complete requested chart, not an exact lower rank or proof of
market availability. Duplicate, malformed, nonnumeric-ID and oversized charts
are errors, not evidence of absence. Rejected responses have zero validated
coverage and an error detail. Original parser validation is reused.

Collection errors return a nonzero exit code **after both CSVs are written**;
both uploads use `always()`. Partial/empty responses are reported without failing
the job. Artifacts are per-run downloads, not an automatically appended history.

## Verification and scope

The existing collector CI runs the offline suite, including targeted matching,
localized titles, partial/missing/error feeds, request counts, CSV round trips,
roster validation and artifact-only behavior:

```sh
cd collector
python -m unittest discover -s tests -v
```

The separate module can also be invoked in a cloud checkout with
`python -m game_observatory.apple_hoyoverse --output data/apple-hoyoverse`;
`--config path/to/roster.json` supplies an alternative roster.

Only the two output CSVs are written by the exporter. No database credentials
or clients, database writes, repository commits, Tableau updates, cron schedule
or historical persistence are part of collection. The workflow has read-only
repository permission and disables checkout credential persistence.
