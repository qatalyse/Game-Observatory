export default function App() {
  return (
    <div className="site-shell">
      <header className="site-header" aria-label="Site header">
        <span className="brand-mark" aria-hidden="true" />
        <span className="site-name">Game Observatory</span>
      </header>

      <main className="hero">
        <div className="hero-content">
          <div className="eyebrow"><span className="eyebrow-line" /> Gaming analytics portfolio</div>
          <h1>Game Observatory</h1>
          <p className="subtitle">A Tableau and SQL project</p>
          <div className="rule" aria-hidden="true" />
          <p className="supporting-copy">Monitoring games over time.</p>
        </div>
      </main>

      <footer className="site-footer">
        <span>Data and visualizations coming soon.</span>
        <span className="footer-dot" aria-hidden="true" />
        <span>Built for exploration</span>
      </footer>
    </div>
  );
}
