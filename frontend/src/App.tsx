import { useState } from "react";

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
