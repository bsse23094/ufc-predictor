interface ConfidenceBadgeProps {
  score: number;
}

export function ConfidenceBadge({ score }: ConfidenceBadgeProps) {
  let label = "Moderate Confidence";
  let badgeClass = "badge-amber";
  let description = "Balanced analytical indicators across verified career history.";

  if (score >= 0.72) {
    label = "High Confidence";
    badgeClass = "badge-success";
    description = "Extensive common-opponent and high-volume historical bout coverage.";
  } else if (score < 0.55) {
    label = "High Uncertainty";
    badgeClass = "badge-danger";
    description = "Limited recent rounds, weight-class transition, or layoff variance.";
  }

  return (
    <span
      className={`badge ${badgeClass}`}
      title={description}
      aria-label={`Model confidence: ${label} (${(score * 100).toFixed(0)}%)`}
    >
      <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "currentColor" }} />
      {label}
    </span>
  );
}
