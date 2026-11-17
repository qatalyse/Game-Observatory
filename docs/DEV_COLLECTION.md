# Manual Apple collection preview on Vercel

This feature is intended for **temporary developer verification**, not a public
production API or durable historical ingestion. The Apple Markets tab contains
a Run Collection button. A token is entered at run time and kept only in React
component memory; it is never committed, placed in a URL, or stored in local
storage.

## Enable

1. In the Vercel project, go to Settings -> Environment Variables.
2. Create `DEV_COLLECT_TOKEN` with a long randomly generated secret, scoped to
   the environment you are testing (Preview and/or Production).
3. Redeploy the project after changing environment variables.
4. Open the latest Vercel deployment, navigate to Apple Markets, enter the
   secret and click Run Collection.
5. Inspect the four Singapore Top Free genre statuses and download rankings
   or status CSV. Keep CSV files if you need the observations later.

**Never commit or paste this secret into a chat.** The server requires it in
the `X-Dev-Token` header. The API responds with 503 until configured and 401
for invalid tokens. The token is sent over HTTPS. There is no public Run
Collection API without authentication.

## Scope and limitations

- Exactly SG, Top Free, Top 20, Adventure, Role-Playing, Action, Strategy.
- Four upstream requests per click. No persistent storage, cron, database
  writes, Google Sheets writes, or Tableau publication.
- Returned rows represent retrieval-time samples, not Apple's update time.
- Each feed has a status: ok, partial, empty or error. Do not treat a partial
  feed as a complete Top 20 chart.
- All returned games are exported; the dataset is not limited to HoYoverse.
- Results and CSV are returned directly to the browser. The Python function
  is stateless. A browser refresh loses the results unless CSVs were saved.
- Token authentication limits casual abuse but is **not a rate limiter**.
  Keep this endpoint disabled outside verification, or add authenticated
  account-level quotas before wider deployment.
- The Apple legacy RSS source may be unavailable or change response format.

## Endpoint

`POST /api/dev/apple-collect` with `X-Dev-Token` header.
The response contains `rankings`, `statuses`, `rankings_csv`, and
`statuses_csv`. The Vercel rewrite is defined in the root `vercel.json`.
