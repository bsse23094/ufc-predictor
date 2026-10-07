interface RoundDistributionProps {
  rounds: Record<string, number | null | undefined>;
  expectedDurationSeconds?: number;
}

export function RoundDistribution({ rounds, expectedDurationSeconds }: RoundDistributionProps) {
  const roundEntries = Object.entries(rounds).filter(([, v]) => typeof v === "number") as Array<[string, number]>;
  const values = roundEntries.map(([, v]) => v);
  const maxProb = values.length > 0 ? Math.max(...values, 0.01) : 0.01;

  const formatMins = (secs?: number) => {
    if (!secs) return "—";
    const mins = Math.floor(secs / 60);
    const rem = Math.floor(secs % 60);
    return `${mins}m ${rem.toString().padStart(2, "0")}s`;
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "1rem" }}>
        <h3 style={{ fontSize: "1rem", fontWeight: 700, color: "#fff" }}>
          Round & Duration Trajectory
        </h3>
        {expectedDurationSeconds && (
          <span style={{ fontSize: "0.8125rem", color: "var(--color-text-secondary)" }}>
            Exp. Duration: <strong className="num" style={{ color: "#fff" }}>{formatMins(expectedDurationSeconds)}</strong>
          </span>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: `repeat(${roundEntries.length || 1}, 1fr)`, gap: "0.5rem", alignItems: "end", minHeight: "130px" }}>
        {roundEntries.map(([roundKey, prob]) => {
          const heightPct = Math.max(8, (prob / maxProb) * 100);
          const isDec = roundKey.toLowerCase().includes("dec");
          const label = isDec ? "DEC" : `R${roundKey.replace(/\D/g, "") || roundKey}`;

          return (
            <div key={roundKey} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.35rem" }}>
              <span className="num" style={{ fontSize: "0.75rem", color: "var(--color-text-secondary)", fontWeight: 600 }}>
                {(prob * 100).toFixed(1)}%
              </span>
              <div
                style={{
                  width: "100%",
                  height: `${heightPct}%`,
                  minHeight: "12px",
                  background: isDec ? "linear-gradient(180deg, #6366f1, #4338ca)" : "linear-gradient(180deg, #38bdf8, #0284c7)",
                  borderRadius: "4px 4px 0 0",
                  transition: "height 0.4s ease-out",
                }}
                title={`${label}: ${(prob * 100).toFixed(1)}%`}
              />
              <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)" }}>
                {label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
