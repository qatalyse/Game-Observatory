import { useState } from "react";

type Ranking = {
  position: number; position_semantics: string; app_id: string; title: string;
  developer: string; release_date: string; store_url: string; artwork_url: string;
  price_amount: string; price_currency: string; category_id: string; category_label: string;
};
type ChartStatus = {
  feed_type: string; genre: string; status: string; returned_count: number;
  http_status: number | null; error: string; feed_fields: string;
  entry_fields: string; source_url: string;
};
type Collection = { feed_type: string; genre: string; rankings: Ranking[]; statuses: ChartStatus[]; request_count: number };

function downloadCsv(name: string, rows: Ranking[]) {
  const fields = ["position", "position_semantics", "app_id", "title", "developer", "release_date", "store_url", "artwork_url", "price_amount", "price_currency", "category_id", "category_label"];
  const quote = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const csv = [fields.join(","), ...rows.map(row => fields.map(field => quote(row[field as keyof Ranking])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url; link.download = name; document.body.appendChild(link);
  link.click(); link.remove(); URL.revokeObjectURL(url);
}

function AppleDevCollection() {
  const [token, setToken] = useState("");
  const [feedType, setFeedType] = useState("top-grossing");
  const [genre, setGenre] = useState("games");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Collection | null>(null);
  const [error, setError] = useState("");
  async function run() {
    setLoading(true); setError(""); setResult(null);
    try {
      const response = await fetch("/api/dev/apple-collect", {
        method: "POST", headers: { "X-Dev-Token": token, "Content-Type": "application/json" },
        body: JSON.stringify({ feed_type: feedType, genre }),
      });
      const responseText = await response.text();
      let body: Record<string, unknown>;
      try { body = JSON.parse(responseText) as Record<string, unknown>; }
      catch {
        throw new Error(`Vercel returned a non-JSON response (HTTP ${response.status}): ${responseText.trim().slice(0, 240) || "Empty response"}`);
      }
      if (!response.ok) throw new Error(String(body.error || `Collection failed (${response.status})`));
      setResult(body as unknown as Collection);
    } catch (err) { setError(err instanceof Error ? err.message : "Collection failed"); }
    finally { setLoading(false); }
  }
  return (
    <section className="panel dev-panel" aria-label="Developer Apple RSS diagnostics">
      <div className="panel-heading">
        <div><h2>Developer · Apple legacy RSS diagnostics</h2><p>Singapore · Top 20 · Test one feed/category at a time</p></div>
        <span className="panel-status">One request per run</span>
      </div>
      <div className="dev-body">
        <p className="dev-note">Single-request isolation: select a feed and category, then inspect its response. This avoids batching ten large legacy feeds into one serverless invocation.</p>
        <label htmlFor="dev-token">Dev collection token (configured in Vercel)</label>
        <input id="dev-token" type="password" value={token} onChange={event => setToken(event.target.value)} autoComplete="off" placeholder="Enter token" />
        <div className="dev-select-row">
          <label>Feed type<select value={feedType} onChange={event => setFeedType(event.target.value)}><option value="top-grossing">Top Grossing (topgrossingapplications)</option><option value="new-applications">New Applications (newapplications)</option></select></label>
          <label>Category<select value={genre} onChange={event => setGenre(event.target.value)}><option value="games">Games</option><option value="adventure">Adventure</option><option value="role-playing">Role-Playing</option><option value="action">Action</option><option value="strategy">Strategy</option></select></label>
        </div>
        <button className="dev-run" type="button" disabled={!token || loading} onClick={run}>{loading ? "Testing feed…" : "Run Selected Feed Test"}</button>
        {error && <p className="dev-error" role="alert">{error}</p>}
        {result && <div className="dev-results">
          <p className="dev-note">Feed: {result.feed_type} · Category: {result.genre} · Returned {result.rankings.length} entries.</p>
          {result.statuses.map(s => <div className="dev-status" key={s.feed_type + s.genre}>
            <strong>{s.feed_type} · {s.genre}</strong>
            <span>{s.status} · {s.returned_count} entries{s.http_status ? ` · HTTP ${s.http_status}` : ""}</span>
            {s.error && <small>{s.error}</small>}
            <small>Feed fields: {s.feed_fields || "not available"}</small>
            <small>Entry fields: {s.entry_fields || "not available"}</small>
          </div>)}
          <div className="dev-actions"><button type="button" disabled={!result.rankings.length} onClick={() => downloadCsv(`apple_sg_${result.feed_type}_${result.genre}.csv`, result.rankings)}>Download results CSV</button></div>
          <div className="dev-table-wrap"><table className="dev-table"><thead><tr><th>Position</th><th>App</th><th>Category</th><th>Release date</th></tr></thead><tbody>{result.rankings.map(row => <tr key={row.app_id}><td>{row.position}</td><td>{row.title}</td><td>{row.category_label || "—"}</td><td>{row.release_date || "—"}</td></tr>)}</tbody></table></div>
          {result.feed_type === "newapplications" && <p className="dev-note">Position is feed order only; it is not assumed to be rank or chronological release order.</p>}
        </div>}
      </div>
    </section>
  );
}



type Section = "Overview" | "Steam" | "Apple Markets" | "SQL Analysis";

const sections: Section[] = ["Overview", "Steam", "Apple Markets", "SQL Analysis"];

type PanelInfo = {
  title: string;
  description: string;
  emptyLabel: string;
};

const panels: Record<Section, PanelInfo[]> = {
  Overview: [
    { title: "Steam activity", description: "Concurrent player trends and review activity.", emptyLabel: "Awaiting Steam observations" },
    { title: "Apple market rankings", description: "Rank movements across supported storefronts.", emptyLabel: "Awaiting Apple chart snapshots" },
  ],
  Steam: [
    { title: "Concurrent players", description: "Historical measurements from selected Steam games.", emptyLabel: "No player snapshots collected yet" },
    { title: "Reviews and achievements", description: "Trends derived from public Steam records.", emptyLabel: "No review or achievement data yet" },
  ],
  "Apple Markets": [
    { title: "Rank history", description: "Compare observed chart positions across countries.", emptyLabel: "No historical ranking snapshots yet" },
    { title: "Market comparisons", description: "Chart persistence and changes over time.", emptyLabel: "No market comparisons available yet" },
  ],
  "SQL Analysis": [
    { title: "SQL case studies", description: "Analytical questions, PostgreSQL queries, and findings.", emptyLabel: "Case studies will appear after data validation" },
    { title: "Tableau visualizations", description: "Public dashboards based on curated SQL results.", emptyLabel: "Tableau dashboards not published yet" },
  ],
};

function DashboardPanel({ title, description, emptyLabel }: PanelInfo) {
  return (
    <section className="panel" aria-label={title}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <span className="panel-status">Pending data</span>
      </div>
      <div className="panel-empty">
        <span className="empty-symbol" aria-hidden="true">▤</span>
        <p>{emptyLabel}</p>
      </div>
    </section>
  );
}

export default function App() {
  const [activeSection, setActiveSection] = useState<Section>("Overview");

  return (
    <div className="site-shell">
      <header className="site-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div className="brand-text">
            <span className="site-name">Game Observatory</span>
            <span className="site-subtitle">A Tableau and SQL project</span>
          </div>
        </div>
        <span className="header-note">Monitoring games over time</span>
      </header>

      <nav className="site-nav" aria-label="Dashboard sections">
        {sections.map((section) => (
          <button
            key={section}
            type="button"
            aria-current={activeSection === section ? "page" : undefined}
            className={activeSection === section ? "nav-link active" : "nav-link"}
            onClick={() => setActiveSection(section)}
          >
            {section}
          </button>
        ))}
      </nav>

      <main className="dashboard">
        <div className="page-heading">
          <div>
            <h1>{activeSection}</h1>
            <p>{activeSection === "Overview"
              ? "A view of gaming activity and market trends."
              : activeSection === "Steam"
                ? "Player activity, public reviews, and achievements."
                : activeSection === "Apple Markets"
                  ? "App Store ranking observations across markets."
                  : "Queries and Tableau visualizations backed by real data."}
            </p>
          </div>
          <span className="page-status"><span className="status-dot" /> Data pipeline not connected</span>
        </div>

        {activeSection === "Apple Markets" && <AppleDevCollection />}

        <div className="panel-grid">
          {panels[activeSection].map((panel) => (
            <DashboardPanel key={panel.title} {...panel} />
          ))}
        </div>
      </main>

      <footer className="site-footer">
        <span>Game Observatory</span>
        <span>Data collection and Tableau integration are upcoming.</span>
      </footer>
    </div>
  );
}
