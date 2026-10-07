import type { FighterDetail } from "@ufc-predictor/shared-types";

interface TaleOfTheTapeProps {
  fighterA: FighterDetail;
  fighterB: FighterDetail;
  onSwap?: () => void;
}

export function TaleOfTheTape({ fighterA, fighterB, onSwap }: TaleOfTheTapeProps) {
  const rows: Array<{
    label: string;
    valA: string | number;
    valB: string | number;
    diff?: string;
  }> = [
    {
      label: "Stance",
      valA: fighterA.stance || "Orthodox",
      valB: fighterB.stance || "Orthodox",
    },
    {
      label: "Height",
      valA: fighterA.height_cm ? `${fighterA.height_cm} cm` : "—",
      valB: fighterB.height_cm ? `${fighterB.height_cm} cm` : "—",
      diff:
        fighterA.height_cm && fighterB.height_cm
          ? `${fighterA.height_cm >= fighterB.height_cm ? "+" : ""}${fighterA.height_cm - fighterB.height_cm} cm`
          : undefined,
    },
    {
      label: "Reach",
      valA: fighterA.reach_cm ? `${fighterA.reach_cm} cm` : "—",
      valB: fighterB.reach_cm ? `${fighterB.reach_cm} cm` : "—",
      diff:
        fighterA.reach_cm && fighterB.reach_cm
          ? `${fighterA.reach_cm >= fighterB.reach_cm ? "+" : ""}${fighterA.reach_cm - fighterB.reach_cm} cm`
          : undefined,
    },
    {
      label: "Career Record",
      valA: fighterA.stats ? `${fighterA.stats.wins ?? 0}-${fighterA.stats.losses ?? 0}-${fighterA.stats.draws ?? 0}` : "—",
      valB: fighterB.stats ? `${fighterB.stats.wins ?? 0}-${fighterB.stats.losses ?? 0}-${fighterB.stats.draws ?? 0}` : "—",
    },
    {
      label: "Finish Ratio (KO/Sub)",
      valA: fighterA.stats ? `${(fighterA.stats.ko_wins || 0) + (fighterA.stats.sub_wins || 0)} / ${fighterA.stats.wins || 1}` : "—",
      valB: fighterB.stats ? `${(fighterB.stats.ko_wins || 0) + (fighterB.stats.sub_wins || 0)} / ${fighterB.stats.wins || 1}` : "—",
    },
    {
      label: "Strikes Landed / Min",
      valA: (fighterA.stats?.sig_strike_landed_per_min || 0).toFixed(2),
      valB: (fighterB.stats?.sig_strike_landed_per_min || 0).toFixed(2),
      diff: `${(fighterA.stats?.sig_strike_landed_per_min || 0) >= (fighterB.stats?.sig_strike_landed_per_min || 0) ? "+" : ""}${(
        (fighterA.stats?.sig_strike_landed_per_min || 0) - (fighterB.stats?.sig_strike_landed_per_min || 0)
      ).toFixed(2)}`,
    },
    {
      label: "Strikes Absorbed / Min",
      valA: (fighterA.stats?.sig_strike_absorbed_per_min || 0).toFixed(2),
      valB: (fighterB.stats?.sig_strike_absorbed_per_min || 0).toFixed(2),
      diff: `${(fighterA.stats?.sig_strike_absorbed_per_min || 0) >= (fighterB.stats?.sig_strike_absorbed_per_min || 0) ? "+" : ""}${(
        (fighterA.stats?.sig_strike_absorbed_per_min || 0) - (fighterB.stats?.sig_strike_absorbed_per_min || 0)
      ).toFixed(2)}`,
    },
    {
      label: "Striking Defense",
      valA: `${Math.round((fighterA.stats?.sig_strike_def || 0) * 100)}%`,
      valB: `${Math.round((fighterB.stats?.sig_strike_def || 0) * 100)}%`,
    },
    {
      label: "Takedown Avg / 15m",
      valA: (fighterA.stats?.td_avg_per_15m || 0).toFixed(2),
      valB: (fighterB.stats?.td_avg_per_15m || 0).toFixed(2),
    },
    {
      label: "Takedown Defense",
      valA: `${Math.round((fighterA.stats?.td_def || 0) * 100)}%`,
      valB: `${Math.round((fighterB.stats?.td_def || 0) * 100)}%`,
    },
  ];

  return (
    <div className="card" style={{ padding: "1.25rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1rem",
          paddingBottom: "0.75rem",
          borderBottom: "1px solid var(--color-border-subtle)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--color-fighter-a)" }} />
          <h3 style={{ fontSize: "1.125rem", fontWeight: 700, color: "var(--color-fighter-a)" }}>
            {fighterA.display_name || `${fighterA.first_name || ""} ${fighterA.last_name || ""}`.trim() || "Fighter A"}
          </h3>
        </div>

        {onSwap && (
          <button
            onClick={onSwap}
            className="btn btn-secondary"
            style={{ fontSize: "0.75rem", padding: "0.35rem 0.75rem" }}
            aria-label="Swap fighter sides"
          >
            ⇄ Flip Sides
          </button>
        )}

        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <h3 style={{ fontSize: "1.125rem", fontWeight: 700, color: "var(--color-fighter-b)" }}>
            {fighterB.display_name || `${fighterB.first_name || ""} ${fighterB.last_name || ""}`.trim() || "Fighter B"}
          </h3>
          <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--color-fighter-b)" }} />
        </div>
      </div>

      <table className="tott-table" aria-label="Tale of the tape comparison table">
        <thead>
          <tr style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
            <th style={{ textAlign: "right", width: "35%" }}>Fighter A Value</th>
            <th style={{ textAlign: "center", width: "30%" }}>Metric & Signed Differential</th>
            <th style={{ textAlign: "left", width: "35%" }}>Fighter B Value</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="tott-val-a num" style={{ color: "var(--color-text-primary)" }}>
                {r.valA}
              </td>
              <td className="tott-metric">
                <div>{r.label}</div>
                {r.diff && (
                  <div
                    className="num"
                    style={{
                      fontSize: "0.75rem",
                      color: "var(--color-text-secondary)",
                      marginTop: "2px",
                      background: "var(--color-surface-subtle)",
                      display: "inline-block",
                      padding: "1px 6px",
                      borderRadius: "4px",
                    }}
                  >
                    Δ {r.diff}
                  </div>
                )}
              </td>
              <td className="tott-val-b num" style={{ color: "var(--color-text-primary)" }}>
                {r.valB}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
