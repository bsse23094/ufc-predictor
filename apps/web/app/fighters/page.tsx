"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useDivisionStandouts, useFighters } from "@/lib/query/hooks";

function initials(name: string) {
  return name.split(" ").filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

export default function FightersPage() {
  const board = useDivisionStandouts();
  const [division, setDivision] = useState("");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(30);
  const roster = useFighters(search, undefined, limit);
  const rail = useRef<HTMLDivElement>(null);
  const divisions = board.data?.divisions || [];
  const selected = divisions.find((item) => item.code === division) || divisions[0];
  const fighters = roster.data?.items || [];

  return <main className="container fight-home interior-page fighters-page">
    <section className="interior-hero">
      <span className="fight-eyebrow"><span className="live-pip" /> CANONICAL ROSTER / THE ATHLETES</span>
      <h1>BUILT FOR <em>THE CAGE.</em></h1>
      <p>Explore historical division form and search the accepted fighter catalog. Standout cards are derived from recorded bouts, not official UFC rankings.</p>
    </section>

    <section className="fighters-featured">
      <div className="section-heading"><div><span className="section-index">01 / HISTORICAL FORM</span><h2>DIVISION STANDOUTS<span className="red-stop">.</span></h2></div><p>Best recent divisional records by a sample-aware win-rate score. At least three decisive bouts in the three-year window.</p></div>
      {board.isLoading && <div className="card-status" role="status">LOADING DIVISION FORM…</div>}
      {board.isError && <div className="card-status" role="alert">Historical division board unavailable.</div>}
      {selected && <>
        <div className="division-tabs" role="group" aria-label="Weight classes">{divisions.map((item) => <button key={item.code} type="button" className={item.code === selected.code ? "selected" : ""} aria-pressed={item.code === selected.code} onClick={() => { setDivision(item.code); rail.current?.scrollTo({ left: 0, behavior: "smooth" }); }}>{item.label}</button>)}</div>
        <div className="featured-rail-head"><div><span className="section-index">{selected.label.toUpperCase()} / FORM BOARD</span><p>Through {board.data?.as_of_date}; window starts {board.data?.window_start}. Unofficial historical form.</p></div><div className="rail-controls"><button type="button" aria-label="Scroll fighters left" onClick={() => rail.current?.scrollBy({ left: -320, behavior: "smooth" })}>←</button><button type="button" aria-label="Scroll fighters right" onClick={() => rail.current?.scrollBy({ left: 320, behavior: "smooth" })}>→</button></div></div>
        <div className="featured-rail" ref={rail}>{selected.fighters.map((fighter, index) => <article className="featured-fighter" key={fighter.fighter_id}>
          <div className="fighter-art" aria-hidden="true"><span className="fighter-art-rank">{String(index + 1).padStart(2, "0")}</span><div className="fighter-art-octagon" /><strong>{initials(fighter.display_name)}</strong><span className="fighter-art-caption">NO LICENSED PORTRAIT</span></div>
          <div className="featured-fighter-info"><span className="section-index">#{index + 1} / {selected.label.toUpperCase()}</span><h3>{fighter.display_name}</h3><div className="featured-record"><strong>{fighter.wins}-{fighter.losses}</strong><span>DECISIVE BOUTS<br />IN WINDOW</span></div><div className="featured-links"><Link href={`/fighters/${encodeURIComponent(fighter.fighter_id)}`}>PROFILE ↗</Link><Link href={`/compare?fighter_a=${encodeURIComponent(fighter.fighter_id)}`}>PREDICT ↗</Link></div></div>
        </article>)}</div>
      </>}
    </section>

    <section className="roster-section"><div className="section-heading"><div><span className="section-index">02 / THE ARCHIVE</span><h2>FIGHTER DIRECTORY<span className="red-stop">.</span></h2></div><p>Search by name to find a canonical fighter profile or start a matchup.</p></div>
      <div className="roster-search"><label htmlFor="roster-query">SEARCH THE ROSTER</label><input id="roster-query" type="search" placeholder="Fighter name…" value={search} onChange={(event) => { setSearch(event.target.value); setLimit(30); }} /><span>{roster.isLoading ? "SEARCHING…" : `${fighters.length} SHOWN`}</span></div>
      {roster.isError && <div className="card-status" role="alert">Fighter directory unavailable: {roster.error.message}</div>}
      {roster.isLoading && <div className="card-status" role="status">SEARCHING CANONICAL ROSTER…</div>}
      {!roster.isLoading && !roster.isError && fighters.length === 0 && <div className="card-status">No fighters match this search.</div>}
      <div className="roster-grid">{fighters.map((fighter) => { const name = fighter.display_name || `${fighter.first_name || ""} ${fighter.last_name || ""}`.trim() || fighter.id; return <article className="roster-card" key={fighter.id}><div className="roster-avatar" aria-hidden="true">{initials(name)}</div><div><span>CANONICAL FIGHTER</span><h3>{name}</h3></div><div className="roster-actions"><Link href={`/fighters/${encodeURIComponent(fighter.id)}`}>PROFILE ↗</Link><Link href={`/compare?fighter_a=${encodeURIComponent(fighter.id)}`}>PREDICT ↗</Link></div></article>; })}</div>
      {roster.data?.has_more && <button type="button" className="roster-more" onClick={() => setLimit((current) => current + 30)}>LOAD MORE FIGHTERS ↓</button>}
    </section>
    <div className="home-endnote">DIVISION STANDOUTS ARE DATA-DERIVED HISTORICAL FORM, NOT OFFICIAL UFC RANKINGS.</div>
  </main>;
}
