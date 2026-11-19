const rankRangeCalculation = `// Rank Range Label
// Display highest and lowest rankings cross markets

IF MIN([Rank]) = WINDOW_MAX(MIN([Rank]))
AND INDEX() = WINDOW_MIN(
    IF MIN([Rank]) = WINDOW_MAX(MIN([Rank]))
    THEN INDEX()
    END
)
THEN
    IF WINDOW_MIN(MIN([Rank])) = WINDOW_MAX(MIN([Rank]))
    THEN
        "Rank: " + STR(INT(WINDOW_MIN(MIN([Rank]))))
    ELSE
        "Rank Range: " +
        STR(INT(WINDOW_MIN(MIN([Rank])))) +
        " - " +
        STR(INT(WINDOW_MAX(MIN([Rank]))))
    END
END`;

export default function TableauCalculations() {
  return (
    <section className="panel tableau-calculations" aria-label="Tableau Calculations">
      <div className="panel-heading">
        <div>
          <h2>Tableau Calculations</h2>
          <p>Calculated fields used in the dashboard.</p>
        </div>
      </div>
      <div className="calculation-body">
        <pre tabIndex={0} aria-label="Rank Range Label calculation"><code>{rankRangeCalculation}</code></pre>
      </div>
    </section>
  );
}
