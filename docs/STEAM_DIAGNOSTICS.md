# Manual Steam concurrent-player diagnostics

This diagnostic checks the 19 configured Steam apps on demand. It uses the
official [ISteamUserStats/GetNumberOfCurrentPlayers/v1](https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetNumberOfCurrentPlayers)
method via the public Steam Web API host:

```text
GET https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=413150
```

This method needs no Steam API key. Counts cover players currently active in
that app and connected to Steam. They exclude offline players and other PC
launchers, mobile and console platforms. They are neither daily/monthly active
users nor a game's total audience. The API does not supply historical counts
or a measurement timestamp; UTC timestamps record our retrieval attempts.

## Fixed diagnostic catalogue

| Title | Steam App ID |
| --- | --- |
| Honkai Impact 3rd | 1671200 |
| Zenless Zone Zero | 4162040 |
| Wuthering Waves | 3513350 |
| Punishing Gray Raven | 4125930 |
| Tower of Fantasy | 2064650 |
| Neverness to Everness | 4508340 |
| inZOI | 2456740 |
| Loftia | 2320980 |
| Stardew Valley | 413150 |
| The Sims 4 | 1222670 |
| The Sims 3 | 47890 |
| [Heartopia](https://store.steampowered.com/app/4025700/) | 4025700 |
| [Arknights: Endfield](https://store.steampowered.com/app/4732690/) | 4732690 |
| [Persona5: The Phantom X](https://store.steampowered.com/app/3061570/) | 3061570 |
| [Where Winds Meet](https://store.steampowered.com/app/3564740/) | 3564740 |
| [Reverse: 1999](https://store.steampowered.com/app/3092660/) | 3092660 |
| [AFK Journey](https://store.steampowered.com/app/4195600/) | 4195600 |
| [Dressmaker](https://store.steampowered.com/app/4019220/) | 4019220 |
| [Disney Dreamlight Valley](https://store.steampowered.com/app/1401590/) | 1401590 |

The six additions from Heartopia through AFK Journey were verified against their
official Steam store pages on 2026-11-19. Dressmaker and Disney Dreamlight Valley
were verified on 2026-11-20. P5X is listed as Persona5: The Phantom X. The Sims 2 Legacy
Collection (3314070) is no longer requested; previously exported artifacts
remain unchanged.

These user-selected mappings are configured in `collector/game_observatory/steam.py`
and mirrored in `frontend/src/SteamDevCollection.tsx`; a test checks the mapping.
An unavailable response does not establish that an app is unreleased, delisted,
or has no players. We do not infer release state from this endpoint.

## Run in the website

1. Set the server-side `DEV_COLLECT_TOKEN` environment variable in Vercel and
   redeploy. Use a strong secret; never give it a `VITE_` prefix.
2. Open **Steam**, enter the token, and select any of the 19 games.
3. Click **Check selected games**. At least one game and a token are required.
4. Inspect each game's count, status, HTTP/Steam result codes and UTC time.

The token lives only in component memory and travels in `X-Dev-Token`; it is
not embedded in the frontend bundle, placed in URLs, or saved in browser storage.
The UI disables repeat clicks while running and makes no request on page load,
selection changes or a timer. It clears earlier results when starting a new run.
Switching away from the Steam section discards the panel's token and results.

## Endpoint contract

Vercel rewrites `POST /api/dev/steam-collect` to `api/steam_collect.py` and
explicitly packages the collector alongside it. Its maximum duration is 60 seconds.
The underlying `/api/steam_collect` and `/api/steam_collect.py` paths enforce the
same authentication. Every response uses `Cache-Control: no-store`.

```bash
curl -X POST 'https://YOUR-DEPLOYMENT/api/dev/steam-collect' \
  -H "X-Dev-Token: $DEV_COLLECT_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"app_ids":["3513350","413150"]}'
```

`app_ids` is required: a non-empty JSON array of unique **string** IDs from the
catalogue, maximum 19. Unknown IDs, duplicates, numeric values, null, malformed
JSON, negative/invalid content lengths, transfer encoding and extra object keys
are rejected before collection. The body limit is 2,048 bytes.

| HTTP status | Meaning |
| --- | --- |
| 200 | Diagnostic completed; inspect each result, even if every app failed |
| 400 | Invalid body or selection |
| 401 | Missing or incorrect token |
| 404 | Unknown POST route |
| 405 | GET does not run collection; use POST |
| 413 | Request exceeds the body limit |
| 503 | Token is not configured; collection is disabled |
| 502 | Unexpected failure of the overall diagnostic |

Successful responses include `run_id`, `source`, `started_at_utc`,
`completed_at_utc`, `app_ids_selected`, `request_count`, `success_count`, an overall
`status` (`ok`, `partial`, `no_data`) and one `results` row per selected app, in
selection order. `no_data` means none supplied a valid count; it does not mean
zero players. Each row contains:

- `snapshot_id`, `run_id`, `app_id`, `title`, `source`, `source_url`.
- `started_at_utc`, `retrieved_at_utc`: start and completion of that app's attempt,
  including failures. These are locally observed times, not Steam measurement times.
- `player_count`: a nonnegative integer only for `ok`, otherwise null.
- `http_status`: upstream HTTP status when received, otherwise null.
- `steam_result`: integer Steam result code when parsed, otherwise null.
- `status`: `ok`, `unavailable` or `error`.
- `error_code`, `error`: an empty string on success; otherwise an explicit outcome.

`ok` requires HTTP 200, integer `response.result == 1`, and a nonnegative integer
`response.player_count`. Booleans, strings, negative values, missing fields and
invalid JSON are rejected. **Zero is a valid observed count.** A non-success
integer Steam result produces `unavailable` / `steam_unavailable`, with no count.
Request/parse failures produce `error` with `http_error`, `timeout`,
`network_error`, `invalid_response` or `unexpected_error`. Network/internal
exception details are not returned to the browser.

The collector uses only the Python standard library, at most three concurrent
workers, an eight-second network timeout per request and a 64 KiB response limit.
It makes exactly one attempt per app, with no retries; one app's failure cannot
discard other results. The browser stops waiting after 55 seconds. This is a
diagnostic, so transient failures should be retried manually.

## Manual Steam CSV export in GitHub Actions

Open **Actions → Export Steam player test dataset → Run workflow**, select
`main`, then select **Run workflow**. The export executes on GitHub's hosted
runner; it does not need a local checkout, Steam API key, Vercel token or database
credentials. It requests the current player count once for every configured game
(currently 19) using the existing Steam collector.

Download the two artifacts from the completed run page (retained for 30 days):

- `steam-current-players` contains `steam_players.csv`: one row per successful
  Steam observation, including observed zero counts. Maximum one row per game.
- `steam-player-statuses` contains `steam_statuses.csv`: one outcome per
  configured game, including HTTP, timeout, parse and unavailable outcomes.

Both files share `snapshot_id`, `run_id`, `app_id`, `title`, `player_count`,
`started_at_utc`, `retrieved_at_utc`, `source` and `source_url`. The statuses
file additionally includes `http_status`, `steam_result`, `status`,
`error_code` and `error`. Join the files on `snapshot_id`; `run_id` identifies
the whole collection. All retrieval times are UTC. Failed/unavailable player
counts are blank CSV cells, never fabricated zeroes.

The separate `game_observatory.steam_test_dataset` entry point reuses
`steam.collect()` and leaves the existing diagnostic CLI, endpoint and frontend
unchanged. It always writes both CSVs after collection, including a header-only
players file when no app provides data. Unavailable Steam results are recorded
without failing the export. Actual request/parse errors produce exit code 1
after the CSVs are written. Verification and both artifact uploads run even
when collection reports errors, so failed runs can still provide diagnostics.
The run summary validates CSV headers, catalogue coverage, IDs, timestamps,
observed counts and matching status records, then lists each game's outcome.

The export workflow has only `workflow_dispatch`: no schedule, push-triggered
Steam requests, database writes or repository data commits. Ordinary CI stays
offline and exercises success, zero, unavailable, mixed/all-error, malformed
response and CSV quoting/overwrite fixtures. This exports a current sample; it
does not obtain historical counts or publish Tableau data.

To run the same export in any Python 3.11+ environment:

```bash
cd collector
python -m game_observatory.steam_test_dataset --output data/steam-test
```

## Run locally

Python 3.11+ and Node.js 22.12+ (or current 24/26) for the frontend tests;
no database, Steam key or third-party Python packages required:

```bash
cd collector
python -m game_observatory.steam                        # all 19 apps
python -m game_observatory.steam --app-ids 3513350,413150 # selected apps
python -m unittest discover -s tests -v
```

The CLI prints the same diagnostic JSON to stdout and writes no files. Exit code
0 means every selected app supplied a valid count; 1 indicates unavailable/error
outcomes; 2 indicates invalid CLI arguments. Importing the module makes no requests.
Installing the collector package also exposes `game-observatory-steam`.

```bash
cd frontend
npm ci
npm test
npm run build
```

`npm run dev` serves only the frontend; `/api/dev/steam-collect` requires Vercel's
function runtime (for example `vercel dev` from the repository root) or a deployed
Vercel preview with the token configured. A Vite-only server does not host Python.

`.github/workflows/steam-diagnostics.yml` runs offline Python/HTTP-handler tests,
frontend interaction tests and the production build on relevant pushes/PRs or
manual dispatch. CI does not call Steam or require secrets. Tests cover the fixed
catalogue, selection validation, successful/zero/unavailable counts, malformed
responses, HTTP/rate-limit/network/timeout failures, bounded response reads,
authentication, direct/rewritten routes, body limits and frontend run controls.

The diagnostic and manual export remain on demand. The separate, opt-in
[Steam daily Sheets workflow](STEAM_DAILY_SHEETS.md) uses the same roster and
CSV exporter. It adds daily history only when enabled; no database migration,
Tableau publication or review/achievement collection is introduced.

## Verification notes (2026-11-18)

The 41 Python tests, seven frontend interaction tests and production build pass
locally. A manual live collector smoke test returned HTTP 200 and valid counts
for all nine configured apps. Counts were transient samples, not saved observations.
These notes record initial local verification. After publication, inspect the
commit's GitHub Actions and Vercel checks for hosted CI and deployment status.

The frontend lockfile pins reproducible dependencies. `npm audit` reports five
high-severity development-tool entries stemming from the same unpatched
`picomatch` ReDoS advisory (GHSA-fc5q-39xc-vjpf) through Vite/Vitest, fdir and
tinyglobby. The registry's latest picomatch is still 4.0.7, within the affected
range; the current test runner removes the older runner's critical findings.
These tools are not shipped in the browser bundle. No forced downgrade or
unsupported dependency override is applied.
