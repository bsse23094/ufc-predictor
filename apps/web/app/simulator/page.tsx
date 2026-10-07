"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FighterSearchSelect } from "@/components/domain/FighterSearchSelect";
import { ProbabilityBar } from "@/components/domain/ProbabilityBar";
import { api } from "@/lib/api/client";
import type { CounterfactualResult, MonteCarloResult } from "@ufc-predictor/shared-types";

function SimulatorContent() {
  const router = useRouter();
  const params = useSearchParams();
  const fighterA = params.get("fighter_a") || "";
  const fighterB = params.get("fighter_b") || "";
  const [nameA, setNameA] = useState("");
  const [nameB, setNameB] = useState("");
  const [reachAdjustment, setReachAdjustment] = useState(0);
  const [rounds, setRounds] = useState<3 | 5>(3);
  const [counterfactual, setCounterfactual] = useState<CounterfactualResult | null>(null);
  const [monteCarlo, setMonteCarlo] = useState<MonteCarloResult | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);

  const navigate = (a: string, b: string) => {
    setCounterfactual(null); setMonteCarlo(null); setError("");
    const next = new URLSearchParams();
    if (a) next.set("fighter_a", a);
    if (b) next.set("fighter_b", b);
    router.push(`/simulator?${next.toString()}`);
  };
  const canRun = Boolean(fighterA && fighterB && fighterA !== fighterB);
  const run = async () => {
    if (!canRun) return;
    setRunning(true); setError(""); setCounterfactual(null); setMonteCarlo(null);
    try {
      const cf = await api.runCounterfactual(fighterA, fighterB, { reach_advantage_cms: reachAdjustment });
      setCounterfactual(cf);
      const mc = await api.runMonteCarlo(fighterA, fighterB, 10000, rounds);
      setMonteCarlo(mc);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Simulation unavailable");
    } finally { setRunning(false); }
  };
  const a = nameA || "Fighter A";
  const b = nameB || "Fighter B";

  return <main className="container fight-home interior-page simulator-page">
    <section className="interior-hero">
      <span className="fight-eyebrow"><span className="live-pip" /> THE LAB / 02</span>
      <h1>CHANGE THE <em>VARIABLES.</em></h1>
      <p>Explore a synthetic reach adjustment and sample winner outcomes from the accepted model. The inputs are hypothetical, and the outputs are research estimates.</p>
      <div className="simulator-hero-index"><span>01 / SET THE FIGHT</span><span>02 / TUNE THE SCENARIO</span><span>03 / RUN THE MODEL</span></div>
    </section>
    <section className="lab-section interior-lab">
      <div className="section-heading"><div><span className="section-index">01 / PARTICIPANTS</span><h2>SET THE FIGHT<span className="red-stop">.</span></h2></div><p>Search the accepted historical roster to choose two distinct fighters.</p></div>
      <div className="matchup-panel"><div className="corner-grid">
        <div className="corner-column corner-red"><span className="corner-kicker">RED CORNER / 01</span><FighterSearchSelect label="Fighter A" corner="a" selectedId={fighterA} selectedName={nameA} disabledId={fighterB} onSelect={(id, name) => { setNameA(name); navigate(id, fighterB); }} /></div>
        <span className="corner-vs">VS</span>
        <div className="corner-column corner-blue"><span className="corner-kicker">BLUE CORNER / 02</span><FighterSearchSelect label="Fighter B" corner="b" selectedId={fighterB} selectedName={nameB} disabledId={fighterA} onSelect={(id, name) => { setNameB(name); navigate(fighterA, id); }} /></div>
      </div></div>
    </section>
    <section className="simulator-controls"><div className="section-heading"><div><span className="section-index">02 / PARAMETERS</span><h2>TUNE THE SCENARIO<span className="red-stop">.</span></h2></div><p>The reach change is synthetic. It does not alter either fighter&apos;s recorded measurements.</p></div>
      <div className="simulator-control-grid">
        <div className="simulator-control-card"><div className="control-card-top"><span>REACH ADVANTAGE / FIGHTER A</span><strong>{reachAdjustment > 0 ? "+" : ""}{reachAdjustment}<small> CM</small></strong></div><input aria-label="Synthetic reach advantage for fighter A" type="range" min={-15} max={15} value={reachAdjustment} onChange={(event) => { setReachAdjustment(Number(event.target.value)); setCounterfactual(null); setMonteCarlo(null); }} /><div className="control-scale"><span>−15 CM</span><span>NO CHANGE</span><span>+15 CM</span></div></div>
        <div className="simulator-control-card"><div className="control-card-top"><span>SCHEDULED ROUNDS</span><strong>0{rounds}<small> RDS</small></strong></div><div className="round-options" role="group" aria-label="Scheduled rounds"><button type="button" className={rounds === 3 ? "selected" : ""} onClick={() => { setRounds(3); setCounterfactual(null); setMonteCarlo(null); }}>03 ROUNDS</button><button type="button" className={rounds === 5 ? "selected" : ""} onClick={() => { setRounds(5); setCounterfactual(null); setMonteCarlo(null); }}>05 ROUNDS</button></div><p>Round selection applies to the outcome sampler. The accepted model estimates winner only.</p></div>
      </div>
      <div className="simulation-action"><button type="button" className="fight-button" disabled={!canRun || running} onClick={run}>{running ? "RUNNING THE MODEL…" : "RUN THE SIMULATION ↗"}</button><span>{canRun ? "10,000 deterministic samples" : "Choose both fighters to continue"}</span></div>
      {error && <div className="error-state" role="alert">Simulation unavailable: {error}</div>}
    </section>
    {(counterfactual || monteCarlo) && <section className="factors-section"><div className="section-heading"><div><span className="section-index">03 / RESULTS</span><h2>THE MODEL OUTPUT<span className="red-stop">.</span></h2></div><p>These are exploratory model outputs under a synthetic scenario, not bout outcome guarantees.</p></div>
      <div className="simulator-result-grid">
        {counterfactual && <div className="simulator-result-card"><span className="section-index">A / SYNTHETIC ADJUSTMENT</span><h3>REACH SCENARIO</h3><div className="result-number">{(counterfactual.counterfactual_probability_a * 100).toFixed(1)}<small>%</small></div><p>Estimated {a} winner probability under the adjustment.</p><ProbabilityBar fighterAName={a} fighterBName={b} fighterAProb={counterfactual.counterfactual_probability_a} fighterBProb={counterfactual.counterfactual_probability_b} showLabels={false} /><div className="result-delta">CHANGE FOR {a.toUpperCase()}: {(counterfactual.probability_delta_a * 100).toFixed(1)} PERCENTAGE POINTS</div>{counterfactual.plausibility_warnings.map((warning) => <p className="result-warning" key={warning}>{warning}</p>)}</div>}
        {monteCarlo && <div className="simulator-result-card"><span className="section-index">B / OUTCOME SAMPLER</span><h3>10,000 TRIALS</h3><div className="result-number blue">{(monteCarlo.win_probability_a * 100).toFixed(1)}<small>%</small></div><p>Sampled {a} winner share across {monteCarlo.iterations.toLocaleString()} trials.</p><ProbabilityBar fighterAName={a} fighterBName={b} fighterAProb={monteCarlo.win_probability_a} fighterBProb={monteCarlo.win_probability_b} showLabels={false} /><div className="result-delta">SEED {monteCarlo.seed} / {rounds} SCHEDULED ROUNDS</div></div>}
      </div>
    </section>}
    <div className="home-endnote">SYNTHETIC INPUTS ARE EXPLORATORY. THE ACCEPTED MODEL SUPPORTS THE WINNER MARKET ONLY.</div>
  </main>;
}

export default function SimulatorPage() {
  return <Suspense fallback={<p className="container">Loading simulator…</p>}><SimulatorContent /></Suspense>;
}
