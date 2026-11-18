# Game Observatory

Monitoring games over time — a SQL & Tableau portfolio project.

## Manual diagnostics

The React frontend includes on-demand Apple legacy RSS checks and Steam
concurrent-player diagnostics. Steam supports nine configured titles with
selected-game controls, per-game counts, statuses and UTC retrieval timestamps.
The Vercel diagnostics require a server-side `DEV_COLLECT_TOKEN`.

See [Steam diagnostics](docs/STEAM_DIAGNOSTICS.md) for setup, the app catalogue,
API contract, local commands and tests, and [Apple diagnostics](docs/DEV_COLLECTION.md).
These diagnostics have no schedules or database writes.

## M1A — Database foundation

This repository contains a PostgreSQL schema designed for Apple App Store ranking snapshots and Steam player, review, and achievement measurements. The manual diagnostics are separate from this schema; remote migrations and scheduled database collection remain disabled.

See [database setup](docs/DATABASE.md) for instructions after the remaining M1A files are committed. **Do not run remote migrations without explicit approval.**
