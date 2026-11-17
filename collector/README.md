# M1B-Apple — legacy Apple RSS diagnostics

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
This does not establish that the feed is a complete catalogue of new games.

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
