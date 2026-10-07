"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FighterSearchSelect } from "@/components/domain/FighterSearchSelect";
import { ProbabilityBar } from "@/components/domain/ProbabilityBar";
import { PredictionExplanationPanel } from "@/components/domain/PredictionExplanationPanel";
import { useFighter, usePrediction, useExplanation, useSimilarMatchups } from "@/lib/query/hooks";

function CompareContent() {
  const router = useRouter();
  const params = useSearchParams();
  const fighterA = params.get("fighter_a") || "";
  const fighterB = params.get("fighter_b") || "";
  const targetDate = params.get("target_fight_date") || undefined;
  const profileA = useFighter(fighterA);
  const profileB = useFighter(fighterB);
  const prediction = usePrediction(fighterA, fighterB, targetDate);
  const explanation = useExplanation(fighterA, fighterB, targetDate, Boolean(prediction.data));
  const similar = useSimilarMatchups(fighterA, fighterB, 4, Boolean(prediction.data));
  const nameA = profileA.data?.display_name || fighterA;
  const nameB = profileB.data?.display_name || fighterB;
  const navigate = (a: string, b: string) => {
    const next = new URLSearchParams();
    if (a) next.set("fighter_a", a);
    if (b) next.set("fighter_b", b);
    if (targetDate) next.set("target_fight_date", targetDate);
    router.push(`/compare?${next.toString()}`);
  };

  return <main className="container fight-home interior-page">
    <section className="interior-hero">
      <span className="fight-eyebrow"><span className="live-pip" /> MATCHUP INTELLIGENCE / 01</span>
      <h1>TALE OF THE <em>TAPE.</em></h1>
      <p>Choose two fighters to examine the accepted winner estimate and the pre-fight numbers behind the matchup.</p>
      {targetDate && <p className="small-meta">Scheduled bout date: {targetDate}. Features are resolved before that date.</p>}
    </section>
    <section className="lab-section interior-lab">
      <div className="section-heading"><div><span className="section-index">01 / BUILD THE FIGHT</span><h2>YOUR CORNERS<span className="red-stop">.</span></h2></div><button className="fight-text-link swap-action" onClick={() => navigate(fighterB, fighterA)} disabled={!fighterA || !fighterB}>SWAP CORNERS ↔</button></div>
      <div className="matchup-panel"><div className="corner-grid">
        <div className="corner-column corner-red"><span className="corner-kicker">RED CORNER / 01</span><FighterSearchSelect label="Fighter A" corner="a" selectedId={fighterA} selectedName={nameA} disabledId={fighterB} onSelect={(id) => navigate(id, fighterB)} /></div>
        <span className="corner-vs">VS</span>
        <div className="corner-column corner-blue"><span className="corner-kicker">BLUE CORNER / 02</span><FighterSearchSelect label="Fighter B" corner="b" selectedId={fighterB} selectedName={nameB} disabledId={fighterA} onSelect={(id) => navigate(fighterA, id)} /></div>
      </div>
      {!fighterA || !fighterB ? <div className="empty-state">SELECT TWO FIGHTERS TO OPEN THE ANALYSIS ↗</div> : null}
      {profileA.isError || profileB.isError ? <div className="error-state">A fighter profile is unavailable.</div> : null}
      {prediction.isLoading ? <div className="empty-state" role="status">SCORING THE MATCHUP…</div> : null}
      {prediction.isError ? <div className="error-state" role="alert">Prediction unavailable: {prediction.error.message}</div> : null}
      {prediction.data && <div className="prediction-content">
        <div className="prediction-heading"><span className="section-index">MODEL VERDICT / WINNER MARKET</span><span className="model-tag">{prediction.data.model_version}</span></div>
        <div className="prediction-numbers"><div><span>{nameA || "RED CORNER"}</span><strong>{(prediction.data.fighter_a_win_prob * 100).toFixed(1)}%</strong></div><div className="predicted-side">ESTIMATED<br />WIN PROBABILITY</div><div><span>{nameB || "BLUE CORNER"}</span><strong>{(prediction.data.fighter_b_win_prob * 100).toFixed(1)}%</strong></div></div>
        <ProbabilityBar fighterAName={nameA} fighterBName={nameB} fighterAProb={prediction.data.fighter_a_win_prob} fighterBProb={prediction.data.fighter_b_win_prob} showLabels={false} />
        <div className="prediction-footer"><span>History cutoff: {prediction.data.prediction_cutoff || "not supplied"}</span><span>Model estimates are uncertain</span></div>
        {prediction.data.limitations?.map((limitation) => <p className="small-meta" key={limitation}>{limitation}</p>)}
      </div>}
      </div>
    </section>
    {prediction.data && <section className="factors-section"><div className="section-heading"><div><span className="section-index">02 / DECISION BREAKDOWN</span><h2>WHERE THE EDGE LIES<span className="red-stop">.</span></h2></div><p>Feature group contributions explain the model estimate. Expand the pre-fight comparison for raw statistical differences.</p></div>
      {explanation.isLoading && <p role="status">Loading pre-fight factors…</p>}
      {explanation.isError && <p role="alert">Factor comparison unavailable.</p>}
      {explanation.data && <PredictionExplanationPanel explanation={explanation.data} fighterAName={nameA} fighterBName={nameB} probabilityA={prediction.data.fighter_a_win_prob} />}
    </section>}
    {prediction.data && similar.data && similar.data.length > 0 && <section className="upcoming-section"><div className="section-heading"><div><span className="section-index">03 / ARCHIVE</span><h2>SIMILAR MATCHUPS<span className="red-stop">.</span></h2></div><p>Historical comparisons for context, not a forecast of how this bout will end.</p></div><div className="event-board">{similar.data.map((item, index) => <div className="bout-row similar-row" key={item.bout_id}><span className="bout-index">{String(index + 1).padStart(2, "0")}</span><span className="bout-names"><b>{item.fighter_a_name}</b><i>vs</i><b>{item.fighter_b_name}</b></span><span className="bout-class">{item.date}</span><span className="bout-action">HISTORICAL</span></div>)}</div></section>}
    <div className="home-endnote">PREDICTIONS ARE ESTIMATES, NOT CERTAINTIES. FOR RESEARCH AND EXPLORATION.</div>
  </main>;
}

export default function ComparePage() {
  return <Suspense fallback={<p className="container">Loading comparison…</p>}><CompareContent /></Suspense>;
}
