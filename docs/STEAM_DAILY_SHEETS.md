# Steam daily retrieval and Sheets

**Daily Steam retrieval and Sheets** adds an independent daily history path.
It reuses `steam.collect()`, the configured 19-game roster and the existing
`steam_test_dataset` CSV exporter. The website selector and manual export use
the same roster, now including Dressmaker (4019220) and Disney Dreamlight
Valley (1401590). See [Steam diagnostics](STEAM_DIAGNOSTICS.md) for source limits.

## Setup and first run

Use the existing Google project, enabled Sheets API, service account and
Workload Identity Federation configuration from [HoYoverse setup](APPLE_DAILY_SHEETS.md).
No new account, project, API key or Google API activation is required in that
same project. Share the Steam spreadsheet with the service account as **Editor**.

Repository **variables** (Settings → Secrets and variables → Actions → Variables):

| Name | Value |
| --- | --- |
| `STEAM_SHEETS_SPREADSHEET_ID` | `1KlPdakbaTFOa5IbMVEy9mxHjQTGs9gwRwFdmGrCVdWA` |
| `GOOGLE_WIF_PROVIDER` | Reuse the existing provider |
| `GOOGLE_SERVICE_ACCOUNT` | Reuse `hoyo-sheets-writer@hoyo-top-grossing-daily.iam.gserviceaccount.com` |
| `STEAM_SHEETS_DAILY_ENABLED` | Leave unset or `false` until manual validation |

Do not replace the HoYoverse variable `GOOGLE_SHEETS_SPREADSHEET_ID`.
Steam never falls back to that variable. Optional Steam-only tab overrides are
`STEAM_SHEETS_PLAYERS_TAB` and `STEAM_SHEETS_STATUSES_TAB`.

1. Merge this PR. Open Actions → **Daily Steam retrieval and Sheets**.
2. Run on `main` with **Upload this snapshot…** unchecked for CSV-only validation.
3. Inspect both downloadable CSVs and the validation output. Expect one status
   per configured title; player rows include successful observations only.
4. Run again on `main` with upload checked. Publishing creates
   `SteamPlayerHistory` and `SteamPlayerStatuses` with exact headers.
   Leave these tabs uncreated before the first upload. An empty `Sheet1` may
   remain or be deleted; the publisher never edits it.
5. Check the two new tabs and the publish result. Enable daily operation only
   after this passes, by setting `STEAM_SHEETS_DAILY_ENABLED` to `true`.

The placeholder schedule is **02:22 Singapore time**, cron `22 18 * * *`.
GitHub scheduling may be delayed; timestamps record actual retrieval.
Unset/false disables automatic Steam requests and uploads. Manual collection
remains available. Publishing is restricted to `main`, matching the existing
Google trust condition. The PR does not enable the variable or perform a live
Google upload.

## Source, schemas and daily history

Each collection makes one Steam current-player request per configured game,
with at most three concurrent requests and the collector's existing timeouts.
It collects a point-in-time Steam-connected player sample, not daily active
users or the total player base. There is no historical Steam backfill endpoint
in this implementation.

Artifacts retain the **exact existing manual CSV schemas** for 30 days:

- `steam_players.csv`: `snapshot_id, run_id, app_id, title, player_count,
  started_at_utc, retrieved_at_utc, source, source_url`.
- `steam_statuses.csv`: those fields plus `http_status, steam_result,
  status, error_code, error`.

Sheets prepends `collection_date, publication_key, record_key` to each:
12 columns in player history, 17 in statuses. IDs remain text, counts/codes
are numeric, and text is written literally rather than evaluated as formulas.
`collection_date` is the Singapore date derived from actual UTC retrieval.
A batch must cover one date, one run, and the complete current roster.
Runs crossing Singapore midnight fail validation rather than being misdated.
Each app has its own snapshot ID and a shared collection run ID; the Actions
run ID is also retained in the artifact name and workflow run page.

A genuine count of zero is saved as 0. An explicit Steam non-success result is
`unavailable`, with a blank count and its result/error detail in statuses.
Such outcomes may be published, including an all-unavailable batch with a
header-only player table. Network, HTTP or parse `error` outcomes retain both
artifacts and fail the run; **no part of that batch is uploaded**. A failed
count is never converted to zero. Player rows must exactly match successful
status rows; malformed, duplicate, missing or mismatched records are rejected
before Google authentication.

The first accepted snapshot for each Singapore date wins. One atomic Sheets
batch appends both tables and a date receipt. Same-date reruns return
`already_published`, without replacing or adding rows, even if counts changed.
Later dates append history. This receipt uses a Steam-specific namespace and
does not alter HoYoverse receipts. Do not edit managed headers or remove the
receipt/tabs: inconsistencies fail closed.

Transient Google errors retry with bounded backoff. After an uncertain write,
the publisher checks the daily receipt before another attempt; concurrent
writers cannot commit the same date twice. A failed upload can use **Re-run
failed jobs** to reuse its original collection artifact (within retention).
Re-running all jobs recollects; it still cannot replace an accepted date.

## Verification and boundaries

Offline tests exercise current-roster requests, manual-schema parity, UTC/date
handling, zero/unavailable/errors, CSV corruption, missing and duplicate records,
dry-run without authentication or extra files, literal cells, atomic initialization,
daily deduplication, next-day append, transient/uncertain writes and rejection.
Hosted CI also validates the workflow gates and upload-only dependency imports.

The manual collector/exporter remain available. HoYoverse collectors, schedules,
spreadsheet destination and publishing logic are unchanged. No database writes,
repository data commits, Tableau updates or browser polling are introduced.

For a Python 3.11+ environment, validation needs only the standard library:
`python -m game_observatory.steam_sheets --input data/steam-daily`.
Explicit `--publish` additionally requires `requirements-sheets.txt` and the
federated credentials supplied by GitHub Actions.
