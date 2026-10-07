import type { MethodProbabilities } from "@ufc-predictor/shared-types";

interface MethodDistributionProps {
  fighterAName: string;
  fighterBName: string;
  methods: MethodProbabilities;
}

export function MethodDistribution({
  fighterAName,
  fighterBName,
  methods,
}: MethodDistributionProps) {
  const formatPct = (val: number) => (val * 100).toFixed(1);

  const items = [
    {
      label: "KO / TKO",
      probA: methods.fighter_a_ko,
      probB: methods.fighter_b_ko,
    },
    {
      label: "Submission",
      probA: methods.fighter_a_sub,
      probB: methods.fighter_b_sub,
    },
    {
      label: "Decision",
      probA: methods.fighter_a_dec,
      probB: methods.fighter_b_dec,
    },
  ];

  return (
    <div className="card">
      <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "1rem", color: "#fff" }}>
        Estimated Finish Path Breakdown
      </h3>
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        {items.map((item) => (
          <div key={item.label}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: "0.8125rem",
                marginBottom: "0.25rem",
              }}
            >
              <span className="num" style={{ color: "var(--color-fighter-a)", fontWeight: 600 }}>
                {fighterAName} {formatPct(item.probA)}%
              </span>
              <span style={{ color: "var(--color-text-secondary)", fontWeight: 500 }}>
                {item.label}
              </span>
              <span className="num" style={{ color: "var(--color-fighter-b)", fontWeight: 600 }}>
                {formatPct(item.probB)}% {fighterBName}
              </span>
            </div>
            <div
              style={{
                height: "10px",
                borderRadius: "var(--radius-full)",
                background: "var(--color-surface-raised)",
                display: "flex",
                overflow: "hidden",
                border: "1px solid var(--color-border-subtle)",
              }}
            >
              <div
                style={{
                  width: `${item.probA * 100}%`,
                  background: "var(--color-fighter-a)",
                  opacity: 0.85,
                }}
              />
              <div style={{ flex: 1 }} />
              <div
                style={{
                  width: `${item.probB * 100}%`,
                  background: "var(--color-fighter-b)",
                  opacity: 0.85,
                }}
              />
            </div>
          </div>
        ))}
      </div>
      <p style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "1rem" }}>
        Paths represent non-exclusive conditional likelihood estimated by the multi-output champion ensemble.
      </p>
    </div>
  );
}
