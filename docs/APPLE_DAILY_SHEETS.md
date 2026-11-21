# Daily Apple collection and Google Sheets

This separate workflow reuses the regional collector from PR #3. The existing
manual exporter stays available and has no Sheets dependency or schedule.

**Automatic retrieval is disabled by default.** The workflow has a daily
11:11 Asia/Singapore placeholder (`11 3 * * *`, 03:11 UTC), but its collection
job skips scheduled events unless the repository variable
`APPLE_SHEETS_DAILY_ENABLED` is exactly `true`. Changing that variable is the
final activation step after regional-data and test-upload validation. The
schedule is in
[apple-hoyoverse-daily-sheets.yml](../.github/workflows/apple-hoyoverse-daily-sheets.yml);
edit its cron line to align with Tableau once its refresh timing is known.
GitHub schedules can run late or miss a run; this is not an exact-time service.
No Tableau refresh or publication is performed.

## Dependencies and validation order

The regional listing fix from PR #3 has been merged. This change targets
`main` and uses roster v4: Adventure contains Genshin and Star Rail;
Role-Playing contains those two plus ZZZ, Honkai Impact 3rd and Tears of Themis;
Action contains ZZZ and Honkai Impact 3rd. Card and Simulation are not requested.
The publisher derives its expected target set from that config and rejects old/different rosters, CSV schemas and
mismatched regional IDs.

1. Use the existing manual collector on this PR's branch to validate a fresh
   three-genre collection: 90 game rows, 30 chart rows, and the correct
   CN/VN regional IDs. Not every title must be ranked for validation to pass.
2. Merge the roster update after that review.
3. Configure a **test spreadsheet** and Google identity below.
4. Manually run **Daily HoYoverse Apple retrieval and Sheets**, leaving
   **publish_to_sheets unchecked**. This collects/validates CSVs with no Google
   access. Download the run artifact containing both CSVs.
5. After confirming regional data, set `APPLE_REGIONAL_VALIDATED=true`. Manually
   dispatch with **publish_to_sheets checked** to test the test spreadsheet.
6. Run it again on the same Singapore date: the upload must report
   `already_published` and leave the row counts unchanged.
7. Point the spreadsheet variable at the intended destination, confirm sharing
   and headers, then set `APPLE_SHEETS_DAILY_ENABLED=true` to activate daily runs.
   Missing/false disables automatic collection and publishing immediately.

A manual run defaults to collection plus dry-run validation. It can be used
even while daily runs are disabled. Publishing requires the explicit manual
checkbox or an enabled scheduled event, successful CSV validation, the regional
validation flag, and Google configuration.

## Google setup (one time, in the cloud)

Scheduled GitHub jobs use a machine identity, not a ChatGPT Google login.
No service-account JSON key is stored in this implementation.

1. Choose a Google Cloud project. Enable the Google Sheets API and the APIs
   required by Google's Workload Identity Federation setup.
2. Create a service account for this spreadsheet publisher.
3. Configure a Workload Identity Pool/provider for GitHub OIDC, and allow that
   identity to impersonate the service account using
   `roles/iam.workloadIdentityUser` on that account. Restrict the provider
   to this repository's numeric identity and intended branch; for production,
   `assertion.repository_id == '1461387739'` and
   `assertion.ref == 'refs/heads/main'`. See Google's
   [GitHub authentication setup](https://github.com/google-github-actions/auth#indirect-wif).
   The publishing job alone receives GitHub `id-token: write` permission.
4. Create the destination Google spreadsheet, and share it with the service
   account email as **Editor**. Do not publish it publicly. The writer creates
   its own two named tabs; leave those names unused, or provide exact headers
   matching the publisher schema if reusing existing managed tabs.
5. Set repository **Actions variables** under Settings → Secrets and variables
   → Actions → Variables:

| Variable | Value |
| --- | --- |
| `GOOGLE_WIF_PROVIDER` | `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL/providers/PROVIDER` |
| `GOOGLE_SERVICE_ACCOUNT` | Service account email |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | ID between `/d/` and `/edit` in the spreadsheet URL |
| `GOOGLE_SHEETS_RANKINGS_TAB` | Optional; defaults to `HoYoRankHistory` |
| `GOOGLE_SHEETS_STATUSES_TAB` | Optional; defaults to `HoYoChartStatuses` |
| `APPLE_REGIONAL_VALIDATED` | Leave unset until PR #3 is validated; then `true` |
| `APPLE_SHEETS_DAILY_ENABLED` | Leave unset until a test upload is validated; then `true` |

The service account needs access to the chosen spreadsheet; broad Google Cloud
Editor/Owner roles are not part of the publisher's design. The Google auth action
creates a temporary credential file on the hosted runner and cleans it up.
Artifacts contain only the two explicitly named CSVs, never credential files.

## Storage and rerun rules

Each default collection makes **30 chart requests** and yields **90 game
records** plus **30 chart records**. CSV artifacts are retained for 30 days even
if collection fails; they are uploaded before the separate publishing job.

- `HoYoRankHistory`: one row per game/market/genre for the accepted daily snapshot.
- `HoYoChartStatuses`: one row per chart in that snapshot.

Both tabs prepend `collection_date, publication_key, record_key` to the collector's
CSV columns. `collection_date` is the **Asia/Singapore date of actual UTC retrieval
timestamps**, not an invented scheduled timestamp. A batch crossing Singapore
midnight is rejected. Missed days are not backfilled with later observations.

Ranks and coverage counts are numeric; App IDs, game IDs and UTC timestamps
remain text. Null ranks are blank cells, never zero or 101. Text is written as
literal strings so titles beginning with `=` cannot become formulas.
Use `game_id` for cross-market grouping and `app_id` for the actual regional
listing. Unknown/outside-chart semantics remain those of the regional collector.
VN Tears of Themis remains an unresolved listing: its rank and App ID stay
blank with `unknown` / `unresolved_market_listing`, even on a complete chart.
Themis uses only existing Role-Playing chart responses; it adds no chart requests.

**First successful upload per Singapore date wins.** Additional collections or
reruns on that date do not append duplicates or replace the accepted snapshot,
even if their source values or roster version differ. If v3 was already
published that day, merging v4 does not replace it; the next Singapore date
uses the expanded scope. Manual CSV artifacts can still show the new scope.
Partial/empty charts and unresolved
listings are valid explicit outcomes; they can be part of that first snapshot.
Any chart request/parse error blocks the entire Sheets upload and fails the job
after preserving CSVs, so collection can be retried before a daily snapshot
is committed. No previous day's data is overwritten.

New tabs, headers, both history tables and a daily receipt in spreadsheet
developer metadata are written in **one atomic Sheets batch**. The receipt has
a deterministic, spreadsheet-unique ID. Concurrent uploads for the same date
cannot both commit; an uncertain response is reconciled against the receipt
before retrying. Transient HTTP/transport failures have bounded exponential
backoff; permission/schema errors fail without blind retries. This relies on
[Sheets atomic batches](https://developers.google.com/workspace/sheets/api/guides/batch)
and [unique metadata IDs](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.developerMetadata).

The workflow also serializes its own runs. Other spreadsheet tabs are untouched.
Keep these two tabs and their headers managed by this writer; do not remove
daily receipts, rename/delete managed tabs, or insert unrelated records there.
A receipt/header collision fails closed. Editing a previously accepted snapshot
is a separate, deliberate correction operation and is not automated here.

## Failure recovery and cloud commands

The artifact is named `apple-hoyoverse-daily-RUN_ID-ATTEMPT`; it contains
`apple_hoyoverse_rankings.csv` and `apple_hoyoverse_chart_statuses.csv`.

- Collection error: inspect retained chart statuses; retry the manual workflow
  when the source recovers. No Sheets write occurs.
- Authentication/sharing/configuration error: fix the setup, then rerun. CSVs
  from the collection job remain downloadable.
- Ambiguous upload/timeout: rerun; the atomic daily receipt prevents duplicates.
- Header or receipt inconsistency: stop and inspect the managed spreadsheet.
  Do not delete only the receipt and retry, which would bypass history protection.

In an authorized cloud checkout, validate saved CSVs without Google access:

```sh
cd collector
python -m game_observatory.apple_sheets --input data/apple-hoyoverse
```

To publish saved CSVs from that checkout, install `requirements-sheets.txt`,
provide Google application credentials and the spreadsheet ID, then add
`--publish`. The date is derived from those saved observations, allowing upload
recovery without assigning old observations a new date. Default CLI behavior
never authenticates or writes to Google.

Offline unit tests use an atomic fake Sheets service, including timeout-after-
commit and concurrent-writer scenarios. CI also installs/imports the optional
Google authentication dependency and parses the gated workflow. No real sheet
write, live Google authorization, schedule activation, database write, or
Tableau update is performed by CI.

## Import an earlier manual snapshot

Use **Actions → Import saved HoYoverse Apple history → Run workflow** on
`main`. This separate workflow has no schedule. Its defaults select the
November 19, 2026 export already validated during setup:

| Input | Value |
| --- | --- |
| `source_run_id` | `44489555279` |
| `collection_date` | `2026-11-19` |
| `publish_to_sheets` | unchecked for validation; checked for an explicit upload |

The source must be a completed, successful run of the manual targeted
exporter in this repository. Its latest attempt supplies the two named CSV
artifacts. Expired/missing artifacts fail the preparation job. Older roster
versions are rejected rather than silently converted to the current roster.

Preparation checks the exact CSV headers, current roster, full configured
game/chart set, joins, original run/attempt and Singapore collection date.
The requested date must be earlier than today's Singapore date and must match
the saved observations. It never fetches fresh Apple charts or rewrites dates,
ranks, timestamps, snapshot IDs or source metadata. A source chart error blocks
publication; explicit partial charts and unresolved listings remain valid.

Leave publishing unchecked for the first validation. Then run it again with
publishing checked to import through the existing Sheets publisher. The same
Google identity, destination variables and regional-validation flag apply.
Publishing is restricted to `main` and shares concurrency with daily publishing.
No credentials are obtained during preparation or a dry run.

The publisher adds `collection_date, publication_key, record_key` and atomically
writes the usual receipt. An accepted date is never replaced; importing it
again reports `already_published`. Importing November 19 after November 20 adds
the earlier date without changing today's rows or receipt.

History is append-only: the older batch appears after existing rows in the
physical sheet. Use `collection_date` to sort the whole table or the Tableau
view chronologically. Do not paste raw exports directly into these managed tabs.

Validated transfer artifacts use the import run ID without its attempt and
are replaced on a full retry. Retrying only the historical publishing job can
reuse preparation. The original daily workflow still uses attempt-specific
artifact names: use a fresh manual daily run or rerun all jobs when recovering
that workflow. Importing old CSVs neither enables nor changes the daily schedule.
