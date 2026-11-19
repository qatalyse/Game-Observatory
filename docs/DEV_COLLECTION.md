# Manual Apple legacy RSS diagnostics on Vercel

For the separate token-protected Steam endpoint and selected-game panel, see
[Steam concurrent-player diagnostics](STEAM_DIAGNOSTICS.md). Both use the
server-side `DEV_COLLECT_TOKEN`. The Apple frontend remains a manual diagnostic
and does not write to a database or publish Tableau data.

The Apple Markets panel tests one selected market/feed/category per click.

1. Set `DEV_COLLECT_TOKEN` in Vercel and redeploy.
2. Open Apple Markets and enter the token.
3. Choose a market, feed and category.
4. Click **Run Selected Feed Test**.
5. Inspect returned entries, coverage, HTTP/parse status and source metadata.
6. Download the compact result CSV if useful.

Supported markets: SG, US, JP, KR, CN, MY, TH, ID, PH and VN.
Categories: Games (6014), Adventure (7002), Role-Playing (7014),
Simulation (7015), Action (7001), Strategy (7017) and Casual (7003).

## Top Grossing: full Top 100

Every selected Top Grossing category requests `limit=100`. The API calls the
existing collector with `full_chart=True`, so all validated fetched entries
are returned, including games outside the separate targeted roster. Original
positions are preserved. The frontend has no tracked-ID selections, checkboxes,
custom-ID input, rank rounding, +5 buffer or Top 10 fallback. Obsolete request
fields such as `tracked_app_ids` or `depth` cannot change this fixed policy.

A response with 100 valid entries is `ok`; 1–99 entries is `partial`; zero is
`empty`. Invalid/duplicate/oversized charts or failed requests are `error`.
Partial charts keep all valid fetched entries instead of being discarded.
The panel shows actual coverage, for example **23/100 fetched**, and never
claims that an incomplete response establishes a missing game's rank.
No entries or ranks are invented.

Simulation can be inspected directly to investigate whether a title appears
in that market's Simulation Top Grossing chart. An app's displayed category
label is separate source metadata and does not establish membership in every
genre chart. Failing to find a game in an incomplete chart proves no absence.

## New Applications: existing discovery behavior

New Applications still requests 20 and accepts all returned entries, including
responses that exceed 20 (for example 104). Position means feed order, not a
verified rank or release-date sort. For Games, the collector retains only entries
whose own RSS category ID is 6014; source and displayed counts remain separate.

## API scope and other collectors

One upstream request is made per click. The token stays in the request header.
The endpoint validates market/feed/category, caps request bodies at 1 KB and
upstream responses at the existing 2 MB safety limit, and returns compact metadata.
Responses are not cached. Collection failures remain visible in chart statuses;
unexpected server failures return a sanitized error.

The results and CSV filename use the market attached to the returned response,
so changing a selector after retrieval cannot relabel an earlier chart.

This change only bypasses dynamic retention for the frontend Apple API.
The separate targeted tracker/daily workflow and existing full-chart exporters
are independent. The legacy collector CLI remains available for diagnostics.
Steam frontend, endpoint, collector and workflows are unaffected.

These are legacy Apple-hosted endpoints; successful requests do not establish
official documentation or long-term support. No persistence, Tableau publication
or automatic collection is enabled by this frontend.
