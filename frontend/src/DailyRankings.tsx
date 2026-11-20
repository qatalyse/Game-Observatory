export default function DailyRankings() {
  return (
    <section className="panel daily-rankings-panel" aria-label="Daily rankings dashboard">
      <div className="panel-heading">
        <div>
          <h2>Daily rankings over time</h2>
          <p>Follow how game rankings change across markets.</p>
        </div>
        <span className="panel-status">Coming soon</span>
      </div>
      <div className="panel-empty daily-rankings-placeholder">
        <span className="empty-symbol" aria-hidden="true">▤</span>
        <p>A Tableau chart of daily ranking history will appear here.</p>
      </div>
    </section>
  );
}
