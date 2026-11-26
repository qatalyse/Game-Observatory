import { useEffect, useRef, useState } from "react";
import SteamDevCollection from "./SteamDevCollection";
import TableauCalculations from "./TableauCalculations";

type Ranking = {
  position: number; position_semantics: string; app_id: string; title: string;
  developer: string; release_date: string; store_url: string; artwork_url: string;
  price_amount: string; price_currency: string; category_id: string; category_label: string;
};
type ChartStatus = {
  feed_type: string; genre: string; status: string; returned_count: number;
  source_count: number; requested_depth: number; category_filter_id: number | string;
  http_status: number | null; error: string; feed_fields: string;
  entry_fields: string; source_url: string;
};
type Collection = { feed_type: string; genre: string; country: string; rankings: Ranking[]; statuses: ChartStatus[]; request_count: number };

function downloadCsv(name: string, rows: Ranking[]) {
  const fields = ["position", "position_semantics", "app_id", "title", "developer", "release_date", "store_url", "artwork_url", "price_amount", "price_currency", "category_id", "category_label"];
  const quote = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const csv = [fields.join(","), ...rows.map(row => fields.map(field => quote(row[field as keyof Ranking])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url; link.download = name; document.body.appendChild(link);
  link.click(); link.remove(); URL.revokeObjectURL(url);
}

function TableauDashboard() {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [frameScale, setFrameScale] = useState(1);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const fitDashboard = () => setFrameScale(Math.min(1, viewport.getBoundingClientRect().width / 1068));
    fitDashboard();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(fitDashboard);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  return (
    <section className="panel tableau-panel" aria-label="Tableau Public dashboard">
      <div className="panel-heading">
        <div>
          <h2>Gaming Industry Insights</h2>
          <p>Current display: Concurrent Steam player monitoring (selected games) | App Store cross market top grossing ranking | 7 day top grossing ranking</p>
        </div>
        <a className="apple-store-link" href="https://public.tableau.com/views/GameMarketDataanalytics/Dashboard1" target="_blank" rel="noreferrer">Open in Tableau Public</a>
      </div>
      <div className="tableau-viewport" ref={viewportRef}>
        <iframe
          className="tableau-frame"
          style={{ transform: `scale(${frameScale})` }}
          title="Game Observatory - Apple Top Grossing Adventure Rankings"
          aria-describedby="tableau-disclaimer"
          src="https://public.tableau.com/views/GameMarketDataanalytics/Dashboard1?:showVizHome=no&:embed=yes&:toolbar=no&:tabs=no"
          loading="lazy"
          allowFullScreen
          scrolling="no"
        />
      </div>
      <p className="tableau-disclaimer" id="tableau-disclaimer">Figures shown do not represent the full player base or overall market distribution, particularly for games available on multiple platforms.</p>
    </section>
  );
}
function AppleDevCollection() {
  const [token, setToken] = useState("");
  const [feedType, setFeedType] = useState("top-grossing");
  const [genre, setGenre] = useState("games");
  const [market, setMarket] = useState("SG");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Collection | null>(null);
  const [error, setError] = useState("");
  async function run() {
    setLoading(true); setError(""); setResult(null);
    try {
      const response = await fetch("/api/dev/apple-collect", {
        method: "POST", headers: { "X-Dev-Token": token, "Content-Type": "application/json" },
        body: JSON.stringify({ feed_type: feedType, genre, market }),
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
        <div><h2>Developer · Apple legacy RSS diagnostics</h2><p>10 Apple storefronts · Top Grossing 100 / New Applications 20 requested</p></div>
        <span className="panel-status">One request per run</span>
      </div>
      <div className="dev-body">
        <p className="dev-note">Select one market, feed and category. Top Grossing shows all fetched entries from the requested Top 100; partial charts show their actual coverage.</p>
        <label htmlFor="dev-token">Dev collection token (configured in Vercel)</label>
        <input id="dev-token" type="password" value={token} onChange={event => setToken(event.target.value)} autoComplete="off" placeholder="Enter token" />
        <div className="dev-select-row">
          <label>Market<select value={market} onChange={event => setMarket(event.target.value)}>
            <option value="SG">Singapore</option><option value="US">United States</option>
            <option value="JP">Japan</option><option value="KR">South Korea</option>
            <option value="CN">China</option><option value="MY">Malaysia</option>
            <option value="TH">Thailand</option><option value="ID">Indonesia</option>
            <option value="PH">Philippines</option><option value="VN">Vietnam</option>
          </select></label>
          <label>Feed type<select value={feedType} onChange={event => setFeedType(event.target.value)}><option value="top-grossing">Top Grossing (topgrossingapplications)</option><option value="new-applications">New Applications (newapplications)</option></select></label>
          <label>Category<select value={genre} onChange={event => setGenre(event.target.value)}><option value="games">Games</option><option value="adventure">Adventure</option><option value="role-playing">Role-Playing</option><option value="simulation">Simulation</option><option value="action">Action</option><option value="strategy">Strategy</option><option value="casual">Casual</option></select></label>
        </div>
        <button className="dev-run" type="button" disabled={!token || loading} onClick={run}>{loading ? "Testing feed…" : "Run Selected Feed Test"}</button>
        {error && <p className="dev-error" role="alert">{error}</p>}
        {result && <div className="dev-results">
          <div className="apple-result-overview">
            <div>
              <span className="apple-eyebrow">{result.country} APP STORE</span>
              <h3>{result.feed_type === "topgrossingapplications" ? "Top Grossing Games" : "New Applications"}</h3>
              <p>{result.genre.replace("-", " ")} · {result.feed_type === "newapplications" ? "20 requested; feed may return more" : "Top 100 requested; all fetched entries shown"} · {result.rankings.length} entries returned</p>
            </div>
            <div className="apple-result-count"><strong>{result.rankings.length}</strong><span>apps returned</span></div>
          </div>
          {result.statuses.map(status => <div className="apple-status-line" key={status.feed_type + status.genre}>
            <span className={status.status === "ok" ? "apple-status-dot ok" : "apple-status-dot warn"} />
            <strong>{status.status.toUpperCase()}</strong>
            <span>HTTP {status.http_status ?? "—"} · {status.returned_count} shown</span>
            {status.source_count > status.returned_count && <span>{status.source_count} source entries</span>}
            {status.category_filter_id && <span>Filtered to Games (6014)</span>}
            {result.feed_type === "topgrossingapplications" && <span>{status.source_count}/{status.requested_depth} fetched</span>}
            {status.error && <span className="dev-error">{status.error}</span>}
          </div>)}
          <div className="dev-actions">
            <button type="button" disabled={!result.rankings.length} onClick={() => downloadCsv(`apple_${result.country.toLowerCase()}_${result.feed_type}_${result.genre}.csv`, result.rankings)}>Download CSV</button>
          </div>
          <div className="apple-results-table-wrap">
            <table className="apple-results-table">
              <thead><tr>
                <th>{result.feed_type === "topgrossingapplications" ? "Rank" : "Feed order"}</th>
                <th>Application</th><th>Release date</th><th>Category</th><th>App price</th><th></th>
              </tr></thead>
              <tbody>{result.rankings.map(row => <tr key={row.app_id}>
                <td className="apple-position">{row.position}</td>
                <td><div className="apple-app-cell">
                  {row.artwork_url ? <img className="apple-app-icon" src={row.artwork_url} alt="" loading="lazy" /> : <span className="apple-app-icon apple-app-placeholder">?</span>}
                  <div className="apple-app-copy">
                    <strong>{row.title}</strong>
                    <span>{row.developer || "Developer unavailable"}</span>
                    <small>ID {row.app_id}</small>
                  </div>
                </div></td>
                <td>{row.release_date || "—"}</td>
                <td>{row.category_label || "—"}</td>
                <td>{row.price_amount ? `${row.price_currency} ${row.price_amount}` : "—"}</td>
                <td>{row.store_url ? <a className="apple-store-link" href={row.store_url} target="_blank" rel="noreferrer">View <span aria-hidden="true">↗</span></a> : "—"}</td>
              </tr>)}</tbody>
            </table>
          </div>
          {result.feed_type === "newapplications" && <p className="dev-note">Position is feed order only; it is not assumed to be rank or chronological release order.</p>}
          <details className="apple-raw-details">
            <summary>Raw feed diagnostics and available fields</summary>
            {result.statuses.map(status => <div className="dev-raw-fields" key={status.feed_type + status.genre}>
              <strong>{status.feed_type} · {status.genre}</strong>
              <small>Feed fields: {status.feed_fields || "not available"}</small>
              <small>Entry fields: {status.entry_fields || "not available"}</small>
              <small>Source: {status.source_url}</small>
            </div>)}
          </details>
        </div>}
      </div>
    </section>
  );
}



type Section = "Overview" | "Steam" | "Apple Markets";

const showSteamTab = import.meta.env.VITE_SHOW_STEAM_TAB === "true";
const showAppleMarketsTab = import.meta.env.VITE_SHOW_APPLE_MARKETS_TAB === "true";
const sections: Section[] = [
  "Overview",
  ...(showSteamTab ? ["Steam" as const] : []),
  ...(showAppleMarketsTab ? ["Apple Markets" as const] : []),
];

type PanelInfo = {
  title: string;
  description: string;
  emptyLabel: string;
};

const panels: Record<Exclude<Section, "Overview">, PanelInfo[]> = {
  Steam: [
    { title: "Concurrent players", description: "Historical measurements from selected Steam games.", emptyLabel: "No player snapshots collected yet" },
    { title: "Reviews and achievements", description: "Trends derived from public Steam records.", emptyLabel: "No review or achievement data yet" },
  ],
  "Apple Markets": [
    { title: "Rank history", description: "Compare observed chart positions across countries.", emptyLabel: "No historical ranking snapshots yet" },
    { title: "Market comparisons", description: "Chart persistence and changes over time.", emptyLabel: "No market comparisons available yet" },
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

function sectionFromUrl(): Section {
  const section = new URLSearchParams(window.location.search).get("section")?.toLowerCase();
  if (section === "steam") return "Steam";
  if (section === "apple-markets") return "Apple Markets";
  return "Overview";
}

export default function App() {
  const [activeSection, setActiveSection] = useState<Section>(sectionFromUrl);
  const embedMode = new URLSearchParams(window.location.search).get("embed") === "true";

  useEffect(() => {
    const syncSection = () => setActiveSection(sectionFromUrl());
    window.addEventListener("popstate", syncSection);
    return () => window.removeEventListener("popstate", syncSection);
  }, []);

  return (
    <div className={embedMode ? "site-shell embed-mode" : "site-shell"}>
      {!embedMode && <header className="site-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div className="brand-text">
            <span className="site-name">Game Observatory</span>
            <span className="site-subtitle">A Tableau dashboard project</span>
          </div>
        </div>
        <span className="header-note">Monitoring games over time</span>
      </header>}

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
              ? "Tableau visualizations based on Steam and App store data"
              : activeSection === "Steam"
                ? "Player activity, public reviews, and achievements."
                : "App Store ranking observations across markets."}
            </p>
          </div>
        </div>

        {activeSection === "Apple Markets" && <AppleDevCollection />}
        {activeSection === "Steam" && <SteamDevCollection />}

        {activeSection === "Overview" ? (
          <div className="overview-layout">
            <TableauDashboard />
            <TableauCalculations />
          </div>
        ) : (
          <div className="panel-grid">
            {panels[activeSection].map((panel) => (
              <DashboardPanel key={panel.title} {...panel} />
            ))}
          </div>
        )}
      </main>

      <footer className="site-footer">
        <span>Game Observatory</span>
        <span>Data collection and Tableau integration refreshed daily.</span>
      </footer>
    </div>
  );
}
