import { useState } from "react";

type Ranking = { country: string; genre: string; rank: number; title: string; app_id: string; retrieved_at_utc: string };
type ChartStatus = { genre: string; status: string; returned_count: number; error: string };
type Collection = { rankings: Ranking[]; statuses: ChartStatus[]; rankings_csv: string; statuses_csv: string };

function downloadCsv(name: string, contents: string) {
  const url = URL.createObjectURL(new Blob([contents], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function AppleDevCollection() {
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Collection | null>(null);
  const [error, setError] = useState("");
  async function run() {
    setLoading(true); setError(""); setResult(null);
    try {
      const response = await fetch("/api/dev/apple-collect", {
        method: "POST", headers: { "X-Dev-Token": token },
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || `Collection failed (${response.status})`);
      setResult(body as Collection);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Collection failed");
    } finally { setLoading(false); }
  }
  return (
    <section className="panel dev-panel" aria-label="Developer Apple RSS collection">
      <div className="panel-heading"><div><h2>Developer · Apple RSS collection</h2><p>Singapore · Top Free · Top 20 · Four genres</p></div><span className="panel-status">Manual test</span></div>
      <div className="dev-body">
        <p className="dev-note">Fetch real rankings for verification. No data is saved to Supabase, Google Sheets or Tableau.</p>
        <label htmlFor="dev-token">Dev collection token (configured in Vercel)</label>
        <input id="dev-token" type="password" value={token} onChange={event => setToken(event.target.value)} autoComplete="off" placeholder="Enter token" />
        <button className="dev-run" type="button" disabled={!token || loading} onClick={run}>{loading ? "Collecting…" : "Run Collection"}</button>
        {error && <p className="dev-error" role="alert">{error}</p>}
        {result && <div className="dev-results">
          <p className="dev-note">Received {result.rankings.length} ranking rows. Check individual chart statuses below.</p>
          <div className="dev-status-grid">{result.statuses.map(s => <div className="dev-status" key={s.genre}><strong>{s.genre}</strong><span>{s.status} · {s.returned_count} rows</span>{s.error && <small>{s.error}</small>}</div>)}</div>
          <div className="dev-actions"><button type="button" onClick={() => downloadCsv("apple_sg_top20_rankings.csv", result.rankings_csv)}>Download rankings CSV</button><button type="button" onClick={() => downloadCsv("apple_sg_chart_statuses.csv", result.statuses_csv)}>Download status CSV</button></div>
          <div className="dev-table-wrap"><table className="dev-table"><thead><tr><th>Genre</th><th>Rank</th><th>Game</th></tr></thead><tbody>{result.rankings.slice(0, 40).map(row => <tr key={`${row.genre}-${row.rank}-${row.app_id}`}><td>{row.genre}</td><td>{row.rank}</td><td>{row.title}</td></tr>)}</tbody></table></div>
          {result.rankings.length > 40 && <p className="dev-note">Showing the first 40 rows. Download CSV for all results.</p>}
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
