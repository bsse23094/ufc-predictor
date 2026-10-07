"use client";

import Link from "next/link";
import { useState } from "react";
import { FighterSearchSelect } from "@/components/domain/FighterSearchSelect";
import { ProbabilityBar } from "@/components/domain/ProbabilityBar";
import { PredictionExplanationPanel } from "@/components/domain/PredictionExplanationPanel";
import { useExplanation, usePrediction, useUpcomingEvent } from "@/lib/query/hooks";

export default function HomePage() {
  const event = useUpcomingEvent();
  const [fighterA, setFighterA] = useState("");
  const [fighterB, setFighterB] = useState("");
  const [nameA, setNameA] = useState("");
  const [nameB, setNameB] = useState("");
  const [fightDate, setFightDate] = useState<string | undefined>();
  const ready = Boolean(fighterA && fighterB && fighterA !== fighterB);
  const prediction = usePrediction(fighterA, fighterB, fightDate, 3, "pure", ready);
  const explanation = useExplanation(fighterA, fighterB, fightDate, Boolean(prediction.data));

  const selectBout = (a: string, b: string, aName: string, bName: string, date: string) => {
    setFighterA(a); setFighterB(b); setNameA(aName); setNameB(bName); setFightDate(date);
    document.getElementById("matchup-lab")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return <main className="fight-home container">
    <section className="fight-hero">
      <div className="fight-hero-copy">
        <span className="fight-eyebrow"><span className="live-pip" /> UFC / PREDICTION LAB</span>
        <h1>THE FIGHT<br /><em>BEFORE</em> THE FIGHT.</h1>
        <p>Put two fighters in the cage. Explore the accepted winner model, the pre-fight numbers, and where the edge may lie.</p>
        <div className="hero-actions"><a className="fight-button" href="#matchup-lab">BUILD A MATCHUP <span>↗</span></a><a className="fight-text-link" href="#upcoming-card">SEE THE CARD ↓</a></div>
      </div>
      <div className="hero-art" aria-hidden="true"><div className="hero-octagon"><span>01</span><strong>VS</strong><span>02</span></div><div className="hero-art-caption">DATA IN THE RED CORNER <b>///</b> 2026 SEASON</div></div>
    </section>
    <div className="ticker-line"><span>PRE-FIGHT INTELLIGENCE</span><span>HISTORICAL MODEL / CANONICAL ROSTER SEARCH</span><span>WINNER MARKET ONLY</span></div>
    <section id="matchup-lab" className="lab-section">
      <div className="section-heading"><div><span className="section-index">01 / THE MATCHUP</span><h2>CHOOSE YOUR CORNERS<span className="red-stop">.</span></h2></div><p>Search the canonical fighter roster or load a matched bout from the upcoming card.</p></div>
      <div className="matchup-panel">
        <div className="corner-grid">
          <div className="corner-column corner-red"><span className="corner-kicker">RED CORNER / 01</span><FighterSearchSelect label="Fighter A" corner="a" selectedId={fighterA} selectedName={nameA} disabledId={fighterB} onSelect={(id, name) => { setFighterA(id); setNameA(name); setFightDate(undefined); }} /></div>
          <span className="corner-vs">VS</span>
          <div className="corner-column corner-blue"><span className="corner-kicker">BLUE CORNER / 02</span><FighterSearchSelect label="Fighter B" corner="b" selectedId={fighterB} selectedName={nameB} disabledId={fighterA} onSelect={(id, name) => { setFighterB(id); setNameB(name); setFightDate(undefined); }} /></div>
        </div>
        {fightDate && <p className="small-meta">Scheduled card date: {fightDate}. Snapshot is resolved as of that date.</p>}
        {!ready && <div className="empty-state">SELECT TWO FIGHTERS TO OPEN THE ANALYSIS ↗</div>}
        {prediction.isLoading && <div className="empty-state" role="status">SCORING THE MATCHUP…</div>}
        {prediction.isError && <div className="error-state" role="alert">Prediction unavailable: {prediction.error.message}</div>}
        {prediction.data && <div className="prediction-content">
          <div className="prediction-heading"><span className="section-index">MODEL VERDICT / WINNER MARKET</span><span className="model-tag">{prediction.data.model_version}</span></div>
          <div className="prediction-numbers"><div><span>RED CORNER</span><strong>{(prediction.data.fighter_a_win_prob * 100).toFixed(1)}%</strong></div><div className="predicted-side">ESTIMATED<br />WIN PROBABILITY</div><div><span>BLUE CORNER</span><strong>{(prediction.data.fighter_b_win_prob * 100).toFixed(1)}%</strong></div></div>
          <ProbabilityBar fighterAName={nameA || prediction.data.fighter_a_name} fighterBName={nameB || prediction.data.fighter_b_name} fighterAProb={prediction.data.fighter_a_win_prob} fighterBProb={prediction.data.fighter_b_win_prob} showLabels={false} />
          <div className="prediction-footer"><span>History cutoff: {prediction.data.prediction_cutoff || "not supplied"}</span><Link href={`/compare?fighter_a=${encodeURIComponent(fighterA)}&fighter_b=${encodeURIComponent(fighterB)}`} className="fight-text-link">FULL COMPARISON ↗</Link></div>
          {prediction.data.limitations?.map((item) => <p className="small-meta" key={item}>{item}</p>)}
        </div>}
      </div>
    </section>
    {prediction.data && <section className="factors-section"><div className="section-heading"><div><span className="section-index">02 / DECISION BREAKDOWN</span><h2>WHY THE MODEL LEANS<span className="red-stop">.</span></h2></div><p>See how accepted model inputs moved the winner estimate, then inspect the underlying pre-fight statistics.</p></div>
      {explanation.isLoading && <p role="status">Loading pre-fight factors…</p>}
      {explanation.isError && <p role="alert">Factor comparison unavailable.</p>}
      {explanation.data && <PredictionExplanationPanel explanation={explanation.data} fighterAName={nameA || prediction.data.fighter_a_name} fighterBName={nameB || prediction.data.fighter_b_name} probabilityA={prediction.data.fighter_a_win_prob} />}
    </section>}
    <section id="upcoming-card" className="upcoming-section"><div className="section-heading"><div><span className="section-index">{prediction.data ? "03" : "02"} / SCHEDULE</span><h2>UPCOMING CARD<span className="red-stop">.</span></h2></div><p>Upcoming bouts appear when a licensed schedule feed is configured. Select a bout whose fighters match the canonical roster.</p></div>
      {event.isLoading && <div className="card-status" role="status">CHECKING THE FIGHT CALENDAR…</div>}
      {event.isError && <div className="card-status"><strong>LIVE CARD UNAVAILABLE</strong><p>No configured schedule feed has provided a verified card. Manual fighter selection remains available above. <a href="https://www.ufc.com/events" target="_blank" rel="noopener noreferrer">See the official calendar ↗</a>.</p></div>}
      {event.data && <div className="event-board"><div className="event-board-head"><div><span className="section-index">{event.data.source_audit_state === "licensed_provider" ? "SPORTSDATAIO / LIVE SCHEDULE" : "LOCAL SCHEDULE / UNVERIFIED"}</span><h3>{event.data.event_name}</h3><span>{event.data.event_date} / {event.data.bouts.length} BOUTS</span></div><Link href="/events" className="fight-text-link">VIEW FULL CARD ↗</Link></div>{event.data.bouts.map((bout, index) => { const a = bout.fighter_a?.display_name || bout.fighter_a_name; const b = bout.fighter_b?.display_name || bout.fighter_b_name; const aId = bout.fighter_a?.fighter_id || bout.fighter_a_id; const bId = bout.fighter_b?.fighter_id || bout.fighter_b_id; return <button className="bout-row" key={bout.id} disabled={!aId || !bId} onClick={() => selectBout(aId, bId, a, b, event.data!.event_date)}><span className="bout-index">{String(index + 1).padStart(2, "0")}</span><span className="bout-names"><b>{a}</b><i>vs</i><b>{b}</b></span><span className="bout-class">{bout.weight_class || "Division TBA"}</span><span className="bout-action">{aId && bId ? "ANALYZE ↗" : "ROSTER MATCH PENDING"}</span></button>; })}</div>}
    </section>
    <div className="home-endnote">PREDICTIONS ARE ESTIMATES, NOT CERTAINTIES. FOR RESEARCH AND EXPLORATION.</div>
  </main>;
}
