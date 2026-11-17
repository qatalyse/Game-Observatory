# Manual Apple legacy RSS diagnostics on Vercel

## Purpose

Temporary, token-protected developer test for Singapore Top 20:
- `topgrossingapplications`
- `newapplications`

Both feed types are tested against Games (6014), Adventure (7002),
Role-Playing (7014), Action (7001), and Strategy (7017). One button click
makes ten upstream requests. The status response includes HTTP status,
entry count, parser status, feed-level fields and the first entry's fields.

## Enable

1. Set `DEV_COLLECT_TOKEN` in Vercel for the environment being tested.
2. Redeploy after changing the variable.
3. Open Apple Markets, enter the token and click Run Collection.
4. Review all ten feed/genre combinations and download both CSV files.

Never commit or share the token.

## Interpret results

- `ok`: exactly the requested depth was returned.
- `partial`: fewer than requested but at least one entry returned.
- `empty`: no entries returned.
- `error`: HTTP, transport, or parsing failure.

A 200 response alone does not validate that the requested semantic is correct.
For `newapplications`, `position` is feed order, not a verified chart rank
or release-date order. Inspect actual release dates and field coverage before
interpreting the list as a chronological new-release catalog.

## Limitations

- Singapore only; Top 20.
- No storage, database writes, Google Sheets writes, Tableau publication,
  cron schedule or automatic collection.
- Ten requests per click; token authentication is not a full rate limiter.
- Feeds are legacy iTunes RSS endpoints; this diagnostic does not establish
  that Apple currently documents or guarantees them.
- Results exist only in the response/browser until the user downloads CSV.
