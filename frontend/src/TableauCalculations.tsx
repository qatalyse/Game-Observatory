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

const playerCountPercentageCalculation = `// Player Count and Percentage Label
// Show the percentage of the table-calculation total,
// followed by the summed player count in parentheses.

STR(ROUND(
    SUM([Player Count])
    / TOTAL(SUM([Player Count])) * 100, 2
))
+ "% ("
+ STR(INT(SUM([Player Count])))
+ ")"`;

const latestCollectionDateCalculation = `// Latest Collection Date
// Find the latest date after extract, data source and context filters.

{ FIXED : MAX([Collection Date]) }`;

const isLatestCollectionDateCalculation = `// Is Latest Collection Date
// Filter this field to True to show the latest available collection date.

[Collection Date] = [Latest Collection Date]`;

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
        <pre tabIndex={0} aria-label="Player Count and Percentage Label calculation"><code>{playerCountPercentageCalculation}</code></pre>
        <pre tabIndex={0} aria-label="Latest Collection Date calculation"><code>{latestCollectionDateCalculation}</code></pre>
        <pre tabIndex={0} aria-label="Is Latest Collection Date calculation"><code>{isLatestCollectionDateCalculation}</code></pre>
      </div>
    </section>
  );
}
