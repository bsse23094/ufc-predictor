import type { ExplanationResult } from "@ufc-predictor/shared-types";

interface Props {
  explanation: ExplanationResult;
  fighterAName: string;
  fighterBName: string;
  probabilityA: number;
}

export function PredictionExplanationPanel({
  explanation, fighterAName, fighterBName, probabilityA,
}: Props) {
  const factors = explanation.model_factors || [];
  const leading = factors.find((factor) => Math.abs(factor.impact_probability_points) >= 0.05);
  const maxImpact = Math.max(5, ...factors.map((factor) => Math.abs(factor.impact_probability_points)));
  const winner = probabilityA >= 0.5 ? fighterAName : fighterBName;
  return <div className="decision-panel">
    <div className="decision-story">
      <div><span className="section-index">THE MODEL&apos;S CALL</span><h3>{winner} has the estimated edge.</h3><p>The accepted winner model gives {fighterAName} {(probabilityA * 100).toFixed(1)}% and {fighterBName} {((1 - probabilityA) * 100).toFixed(1)}%. The factors below show how groups of model inputs moved this estimate from its neutral baseline.</p></div>
      <div className="decision-result"><span>ESTIMATED EDGE</span><strong>{(Math.abs(probabilityA - 0.5) * 100).toFixed(1)}<small> PP</small></strong><p>above 50% for {winner}</p></div>
    </div>
    {leading && <div className="decision-lead"><span>STRONGEST MODEL SIGNAL</span><strong>{leading.factor_name}</strong><p>{leading.impact_probability_points > 0 ? fighterAName : fighterBName} +{Math.abs(leading.impact_probability_points).toFixed(2)} percentage points from this feature group.</p></div>}
    <div className="decision-axis"><span>◀ {fighterAName}</span><span>MODEL IMPACT / PERCENTAGE POINTS</span><span>{fighterBName} ▶</span></div>
    {factors.map((factor) => {
      const value = factor.impact_probability_points;
      return <div className="decision-factor-row" key={factor.factor_name}>
        <div className="decision-factor-label"><strong>{factor.factor_name}</strong><span>{factor.description}</span></div>
        <div className="decision-factor-track" role="img" aria-label={`${factor.factor_name}: ${value > 0 ? fighterAName : fighterBName} ${Math.abs(value).toFixed(2)} percentage points`}><div className="decision-factor-center" /><div className={`decision-factor-fill ${value >= 0 ? "red" : "blue"}`} style={{ width: `${(Math.abs(value) / maxImpact) * 48}%` }} /></div>
        <strong className={value >= 0 ? "decision-impact red" : "decision-impact blue"}>{value > 0 ? "+" : ""}{value.toFixed(2)} PP</strong>
      </div>;
    })}
    <div className="decision-math"><span>SYMMETRIC MODEL BASELINE <strong>{((explanation.model_baseline_probability_a ?? 0.5) * 100).toFixed(1)}%</strong></span><span>FACTOR EFFECTS <strong>{factors.reduce((sum, factor) => sum + factor.impact_probability_points, 0) >= 0 ? "+" : ""}{factors.reduce((sum, factor) => sum + factor.impact_probability_points, 0).toFixed(2)} PP</strong></span><span>FINAL ESTIMATE <strong>{(probabilityA * 100).toFixed(1)}%</strong></span></div>
    <p className="decision-disclaimer">{explanation.disclaimer}</p>
    <details className="snapshot-details"><summary>SEE THE UNDERLYING FIGHTER COMPARISONS</summary><p>These bars are normalized statistical differences from the accepted pre-fight snapshot. They are not model impact estimates.</p><div className="factor-axis"><span>◀ {fighterAName}</span><span>FEATURE GAP</span><span>{fighterBName} ▶</span></div>{explanation.top_factors.map((factor) => <div className="factor-row" key={factor.factor_name}><div className="factor-name"><strong>{factor.factor_name}</strong></div><div className="factor-chart"><div className="factor-midline" /><div className={`factor-fill ${factor.impact_score >= 0 ? "factor-left" : "factor-right"}`} style={{ width: `${Math.min(Math.abs(factor.impact_score), 1) * 48}%` }} /></div><p>{factor.description}</p></div>)}{explanation.missing_data_caveats.map((item) => <p className="small-meta" key={item}>{item}</p>)}</details>
  </div>;
}
