const rankRangeCalculation = `// Display highest and lowest rankings cross markets

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

const playerCountPercentageCalculation = `// Display combined sum and percentage label

STR(ROUND(
    SUM([Player Count])
    / TOTAL(SUM([Player Count])) * 100, 2
))
+ "% ("
+ STR(INT(SUM([Player Count])))
+ ")"`;

const latestCollectionDateCalculation = `// Find the latest extracted date and corresponding data

{ FIXED : MAX([Collection Date]) }

// Filter this field to True to display latest available collection date.
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
        <pre tabIndex={0} aria-label="Latest collection date and filter calculations"><code>{latestCollectionDateCalculation}</code></pre>
      </div>
    </section>
  );
}
