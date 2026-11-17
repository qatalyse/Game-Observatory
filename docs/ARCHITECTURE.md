# Game Observatory architecture

## Goal

Demonstrate PostgreSQL SQL and Tableau using real, continuously collected Steam and Apple gaming data.

## Data flow

```text
Steam / Apple public APIs and feeds
  -> scheduled Python collectors (planned)
  -> PostgreSQL core + raw + ops schemas
  -> SQL analytics views
  -> curated data extracts -> Tableau Public
  -> React/TypeScript website deployed to Vercel
```

The collector, scheduler, frontend, read-only API, and Tableau export are **not implemented in M1A**. Tableau Public does not provide the planned live PostgreSQL database connection; extract publication will be designed separately.

## Schemas

- `core`: countries, canonical games, external app IDs, market mapping, Steam achievement definitions.
- `raw`: historical Apple charts and metadata, Steam players and achievement snapshots, mutable reviews.
- `ops`: collection attempts and outcomes; failed requests must never become zero-valued observations.
- `analytics`: read-only security-invoker SQL views.

No direct browser access to these schemas is planned. The reference repository `qatalyse/mobile-rank-aggregator` is not modified or imported by M1A.

## Milestones

- M1A: local database foundation and schema smoke test (this change).
- M1B/M2: collectors, source validation, safe database writes and scheduler.
- M3: portfolio-grade SQL and Tableau extracts.
- M4: Tableau embeds and website.
- M5: monitoring, backups, recovery and operational readiness.
