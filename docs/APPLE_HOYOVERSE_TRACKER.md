# Manual HoYoverse Apple Top Grossing tracker

This additional exporter leaves the diagnostic collector and full-chart Adventure
exporter unchanged. Open **Actions → Export HoYoverse Apple targeted rankings →
Run workflow**, select the branch containing this workflow, then download both
artifacts from the completed run. GitHub requires a newly added manual workflow
to exist on the default branch before its Run workflow button becomes available.
The collection trigger is `workflow_dispatch` only.

The dedicated [roster config](../collector/game_observatory/apple_hoyoverse.json)
controls genre IDs, game IDs/titles and requested depth (default 100). Markets
come from the existing `apple.MARKETS`: SG, US, JP, KR, CN, MY, TH, ID, PH, VN.
Genre IDs are validated against existing `apple.GENRES`.

| Chart | App IDs |
| --- | --- |
| Adventure (7002) | Genshin Impact 1517783697; Honkai: Star Rail 1599719154 |
| Role-Playing (7014) | Those two; Zenless Zone Zero 1606356401; Honkai Impact 3rd 1336342304; Tears of Themis 1517957388 |

Genshin, Star Rail and ZZZ IDs match existing `apple.TRACKED_GAME_IDS` and the
frontend roster. The other two were absent from existing source/config and are
explicit additions supplied for this tracker. Apple confirms
[Honkai Impact 3rd 1336342304](https://apps.apple.com/us/app/honkai-impact-3rd/id1336342304).
The initially supplied Tears of Themis ID `1425079193` could not be verified.
Apple's [Tears of Themis listing uses 1517957388](https://apps.apple.com/us/app/tears-of-themis/id1517957388);
the dedicated roster uses that verified ID, as confirmed by the requester.
No regional App ID substitution or availability inference is performed. Inclusion is a search target, not a claim
that a title belongs to or appears in either chart in every market. The entry's
primary category does not determine its rank in a requested genre chart.

Apple's legacy RSS endpoint has no App-ID filter. The tracker fetches each
market/genre Top Grossing chart once at limit=100, then matches exact App IDs
locally, preserving the original feed positions. There are **20 chart requests**
and **70 game records** with the default config. No per-game lookup requests,
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
http_status, error, source, source_url, feed_updated_at, feed_fields, entry_fields`.

Game columns: `app_id, title, observed_title, rank, status, store_url`.
`title` is configured; `observed_title` and `store_url` come from the feed.
Unobserved ranks are blank CSV cells (null), never 101.

Chart-only columns: `source_count, chart_complete`. Join files on `snapshot_id`;
`run_id` groups all charts. Each chart gets a unique snapshot ID.
GitHub run IDs include attempt; standalone invocations use a new UUID.
`retrieved_at_utc` records request/attempt completion time in UTC;
`feed_updated_at` is separate source metadata.

| Chart status | Meaning | Absent game status |
| --- | --- | --- |
| complete | HTTP success and exactly the requested number of valid, unique entries | outside-chart |
| partial | Valid nonempty response shorter than requested | unknown |
| empty | Valid feed with zero entries or no entry field | unknown |
| error | HTTP, transport, JSON or entry validation failure | error |

An observed game is `ranked`, including on a partial chart; its
`chart_status` still preserves partial coverage. `outside-chart` only means
absent from this complete requested chart, not an exact lower rank or proof of
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
