# M1B-Apple — HoYoverse-focused App Store collector

This command collects **live Apple legacy iTunes RSS Top Free genre charts** into
portable CSV files. It does not create or modify Supabase tables, Google Sheets,
or Tableau workbooks. It does not require FastAPI: that was needed by the
Mobile Rank Aggregator's interactive live-ranking website, not a batch collector.

## Run locally

Python 3.11+; standard library only.

```bash
cd collector
python -m unittest discover -s tests -v
python -m game_observatory.apple --countries SG --depth 20 --output data/apple
```

For a later ten-country validation:

```bash
python -m game_observatory.apple --countries ALL --depth 20 --output data/apple
```

Defaults: Singapore (SG), Top 20, Top Free, Adventure (7002),
Role-Playing (7014), Action (7001), Strategy (7017). The complete
ten-market allowlist is SG, US, JP, KR, CN, MY, TH, ID, PH, VN.
The `--genres` flag may select a subset. Use one invocation per daily
collection window; **no recurring job is enabled**.

## Outputs

Each invocation emits two separate UTF-8 CSVs with a unique run ID:

- `*_rankings.csv`: one row per returned app position; includes
  observation timestamp (UTC), market, category, App Store ID, title,
  rank and stable per-chart snapshot ID.
- `*_statuses.csv`: one row per requested chart, including `ok`,
  `partial`, `empty` or `error`, the number of returned entries,
  and source URL.

This long-form schema is appropriate for a subsequent SQL/Tableau
transformation. CSV output is **not** persistent production ingestion:
until a storage backend is chosen, generated files are local and
must be retained or archived explicitly.

Apple publishes live charts, not a historical feed. We timestamp the
successful *retrieval*; we cannot claim that Apple updated the ranking
at that moment. A game absent from the Top 20 is **not** assigned
rank 21 or a zero rank. An incomplete response is marked `partial`
and should not be treated as proof that a title is outside the Top 20.

The collector preserves **all returned chart entries**, not only
HoYoverse names. This permits peer comparisons and avoids brittle
name matching. Curated titles of interest:

- Genshin Impact
- Honkai: Star Rail
- Honkai Impact 3rd
- Zenless Zone Zero
- Tears of Themis
- Petit Planet
- Honkai: Nexus Anima
- Varsapura

These are analysis targets, **not confirmed Apple App Store IDs**.
Unreleased/unlisted products cannot be assumed to appear in charts.
Future work: verify official store IDs and title metadata, implement a
storage adapter, schedule daily collection after validation, export an
analytical dataset for Tableau, and publish a first rank-history workbook.

## Source and provenance

Adapted from the Mobile Rank Aggregator's
`backend/app/providers/apple.py` and `docs/DATA_SOURCES.md` on
`feat/ranking-api-integrations`, retaining the legacy feed URL and
category ID mapping. This endpoint is live-only and its behavior and
availability can change. Verify it against actual responses before
enabling automated collection or making public claims about rank.
