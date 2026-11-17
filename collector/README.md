# M1B-Apple — legacy Apple RSS diagnostics

## Manual Adventure Top 50 test dataset

Open **Actions → Extract Apple Adventure test dataset → Run workflow**.
This workflow runs only on manual dispatch. It fetches the legacy iTunes RSS
Top Grossing (`topgrossingapplications`) Adventure (`7002`) Top 50 for SG, US,
JP, KR, CN, MY, TH, ID, PH and VN, using the existing collector and parser.
There are no schedules, Supabase credentials, or database writes.

Download the two artifacts on the completed run page (retained for 30 days):

- `apple-adventure-top50-rankings` contains `apple_rankings.csv`: all fetched,
  validated chart entries, up to 500 rows across the 10 markets.
- `apple-adventure-top50-statuses` contains `apple_statuses.csv`: exactly one
  outcome per market, including HTTP/parse errors, partial and empty charts.

This separate entry point opts into `collect(full_chart=True)` and **does not
apply tracked-game snapshot retention**. Partial charts retain all valid fetched
entries with their original ranks; empty/error feeds have no ranking rows.
`source_count`, `returned_count` and `snapshot_depth` equal the fetched/retained
count; `tracked_app_ids_found` is empty and `limit_behavior` is
`full_chart_returned` for successfully parsed charts. `ok` means all 50 entries,
`partial` means 1–49, `empty` means zero, and `error` records a request or invalid
response failure. Malformed, duplicate or oversized charts are rejected by the
existing strict parser. `snapshot_id` joins each market's rows to its status.

Errors fail the collection step after writing both CSVs; uploads still run so
the results and error details remain downloadable. Partial/empty source outcomes
do not fail the job. The run summary verifies counts and lists market outcomes.
The legacy source may be unavailable or return fewer than 50 entries; no rows
are fabricated. Existing diagnostics, API callers and snapshot policy are unchanged.

Run the same fixed-scope extraction locally with Python 3.11+ (standard library):

```bash
cd collector
python -m game_observatory.apple_test_dataset --output data/apple-test
```

## Existing diagnostics

This collector tests two legacy iTunes RSS feed types in Singapore:
- `topgrossingapplications` (Top Grossing chart)
- `newapplications` (New Applications feed)

Each is tested at Top 20 for the broad Games category (6014) and the
Adventure (7002), Role-Playing (7014), Action (7001), and Strategy (7017)
genre filters. A run makes 10 requests. This is a diagnostics experiment,
not a claim that Apple currently documents or supports these legacy paths.

## Run locally

Python 3.11+; standard library only.

```bash
cd collector
python -m unittest discover -s tests -v
python -m game_observatory.apple --countries SG --depth 20
```

For a later all-market test:
```bash
python -m game_observatory.apple --countries ALL --depth 20
```

Use `--feed-types top-grossing,new-applications` and
`--genres games,adventure,role-playing,action,strategy` to customize tests.

## Data semantics

Every feed request has a separate snapshot ID and status row. Position in
Top Grossing is a chart rank. Position in New Applications is only feed order;
we do not assume the list is sorted by release date or that the order measures
popularity. Release date is captured separately if present.

Top Grossing strictly validates the requested depth. New Applications is a
discovery feed and may ignore the requested limit: all returned entries are
accepted (the observed Singapore response returned 104 entries for limit=20).
The status row records when the requested limit was exceeded but accepted.
This does not establish that the feed is a complete catalogue of new games. For New Applications + Games (6014), entries are additionally filtered using each entry's own RSS category ID because the legacy feed may ignore the URL genre parameter. Source and retained counts are recorded separately, and original feed positions are preserved.

The collector extracts common legacy fields where present: app ID, name,
developer and developer URL, release date, store link, artwork, description,
price/currency, category ID/label, content type, content rating, copyright,
and feed-level updated timestamp and field names. Optional fields may be
absent. Status CSV records top-level feed fields and first-entry field names
for raw schema inspection.

No database or Sheets writes, Tableau publication or scheduled collection
is performed. CSVs are local outputs and require explicit retention.

These feeds are legacy Apple-hosted endpoints and their support/availability
is not guaranteed. Test current HTTP responses, field coverage and category
filter behavior before relying on them. Apple chart data is a retrieval-time
sample; the source does not provide historical snapshots.
