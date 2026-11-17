# Manual Apple legacy RSS diagnostics on Vercel

The Apple Markets developer panel now tests exactly one selected feed/category
per invocation. This isolates unsupported endpoints and avoids oversized
responses or long batches.

1. Set `DEV_COLLECT_TOKEN` in the Vercel environment and redeploy.
2. Open Apple Markets, enter the token.
3. Select Top Grossing or New Applications and one category.
4. Click Run Selected Feed Test.
5. Inspect the returned count, HTTP status, feed fields and entry fields.
6. Download the compact result CSV if useful.

Allowed test scope: Singapore, depth 20, two legacy feed identifiers and
Games/Adventure/Role-Playing/Action/Strategy category filters. One upstream
request per click. The collector rejects upstream JSON bodies larger than 2 MB
and returns only compact metadata to the browser.

Top Grossing enforces the requested Top 20 depth. New Applications accepts
all entries returned by Apple even when the legacy endpoint exceeds the
requested limit (the observed Singapore response returned 104). Its position
is feed order only, not a verified rank or date ordering. The status records
when more entries than requested were accepted.
These are legacy Apple-hosted endpoints; successful requests do not establish
official documentation or long-term support. No persistent storage, Tableau
publication or scheduled jobs are enabled.
