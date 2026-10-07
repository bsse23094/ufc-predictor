interface ProbabilityBarProps {
  fighterAName: string;
  fighterBName: string;
  fighterAProb: number;
  fighterBProb: number;
  showLabels?: boolean;
}

export function ProbabilityBar({
  fighterAName,
  fighterBName,
  fighterAProb,
  fighterBProb,
  showLabels = true,
}: ProbabilityBarProps) {
  const pctA = Math.round(fighterAProb * 1000) / 10;
  const pctB = Math.round(fighterBProb * 1000) / 10;

  return (
    <div style={{ width: "100%" }}>
      {showLabels && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            marginBottom: "0.5rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span
              style={{
                width: "10px",
                height: "10px",
                borderRadius: "2px",
                background: "var(--color-fighter-a)",
                display: "inline-block",
              }}
              aria-hidden="true"
            />
            <span style={{ fontWeight: 700, fontSize: "1rem", color: "var(--color-text-primary)" }}>
              {fighterAName}
            </span>
            <span className="num" style={{ fontWeight: 800, fontSize: "1.125rem", color: "var(--color-fighter-a)" }}>
              {pctA.toFixed(1)}%
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span className="num" style={{ fontWeight: 800, fontSize: "1.125rem", color: "var(--color-fighter-b)" }}>
              {pctB.toFixed(1)}%
            </span>
            <span style={{ fontWeight: 700, fontSize: "1rem", color: "var(--color-text-primary)" }}>
              {fighterBName}
            </span>
            <span
              style={{
                width: "10px",
                height: "10px",
                borderRadius: "2px",
                background: "var(--color-fighter-b)",
                display: "inline-block",
              }}
              aria-hidden="true"
            />
          </div>
        </div>
      )}

      {/* Accessible progressbar track */}
      <div
        className="probability-bar-track"
        role="meter"
        aria-label={`Win probability: ${fighterAName} ${pctA}% vs ${fighterBName} ${pctB}%`}
        aria-valuenow={pctA}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="prob-fill-a"
          style={{ width: `${pctA}%` }}
          title={`${fighterAName}: ${pctA}%`}
        />
        <div
          className="prob-fill-b"
          style={{ width: `${pctB}%` }}
          title={`${fighterBName}: ${pctB}%`}
        />
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "0.75rem",
          color: "var(--color-text-muted)",
          marginTop: "0.35rem",
        }}
      >
        <span>Fighter A (Point-in-time)</span>
        <span>Symmetric constraint: P(A) + P(B) = 100%</span>
        <span>Fighter B (Point-in-time)</span>
      </div>
    </div>
  );
}
