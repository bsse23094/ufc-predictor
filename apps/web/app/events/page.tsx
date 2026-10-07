"use client";

import Link from "next/link";
import { useEvents } from "@/lib/query/hooks";

export default function EventsPage() {
  const events = useEvents("scheduled");
  return <main className="container fight-home interior-page">
    <section className="interior-hero"><span className="fight-eyebrow"><span className="live-pip" /> THE CALENDAR / NEXT UP</span><h1>FIGHTS ON <em>THE HORIZON.</em></h1><p>Browse future UFC cards from the configured schedule feed. A bout can open the winner model when both athletes match the accepted historical roster.</p></section>
    <section className="upcoming-section"><div className="section-heading"><div><span className="section-index">01 / UPCOMING EVENTS</span><h2>THE FIGHT CARDS<span className="red-stop">.</span></h2></div><p>Fight cards can change. The schedule source is identified on each event.</p></div>
      {events.isLoading && <div className="card-status" role="status">CHECKING THE LIVE SCHEDULE…</div>}
      {events.isError && <div className="card-status" role="alert"><strong>SCHEDULE FEED UNAVAILABLE</strong><p>{events.error.message}. Add a provider key to the API environment to activate live cards. You can check the <a href="https://www.ufc.com/events" target="_blank" rel="noopener noreferrer">official UFC calendar ↗</a> and build a matchup manually.</p></div>}
      {events.data?.items.length === 0 && <div className="card-status"><strong>NO VERIFIED FUTURE CARD</strong><p>The licensed provider has not supplied a future card. Check the <a href="https://www.ufc.com/events" target="_blank" rel="noopener noreferrer">official UFC calendar ↗</a>, then <Link href="/compare">build a matchup manually</Link>.</p></div>}
      {events.data?.items.map((event, eventIndex) => <article className="event-board future-event" key={event.event_id}>
        <div className="event-board-head"><div><span className="section-index">{event.source_audit_state === "licensed_provider" ? "SPORTSDATAIO / LIVE SCHEDULE" : "LOCAL FILE / UNVERIFIED"} · CARD {String(eventIndex + 1).padStart(2, "0")}</span><h3>{event.event_name}</h3><span>{event.event_date} / {event.bouts.length} BOUTS</span></div><span className="future-date">{event.event_date}</span></div>
        {event.bouts.length === 0 && <div className="card-status">Bouts have not been published for this card.</div>}
        {event.bouts.map((bout, index) => {
          const nameA = bout.fighter_a?.display_name || bout.fighter_a_name || "Fighter TBA";
          const nameB = bout.fighter_b?.display_name || bout.fighter_b_name || "Fighter TBA";
          const idA = bout.fighter_a?.fighter_id || bout.fighter_a_id;
          const idB = bout.fighter_b?.fighter_id || bout.fighter_b_id;
          const ready = Boolean(idA && idB && idA !== idB);
          const href = `/compare?fighter_a=${encodeURIComponent(idA)}&fighter_b=${encodeURIComponent(idB)}&target_fight_date=${encodeURIComponent(event.event_date)}`;
          return <div className="bout-row future-bout" key={bout.id || `${event.event_id}-${index}`}><span className="bout-index">{String(index + 1).padStart(2, "0")}</span><span className="bout-names"><b>{nameA}</b><i>vs</i><b>{nameB}</b></span><span className="bout-class">{bout.weight_class || "Division TBA"}</span>{ready ? <Link href={href} className="bout-action">PREDICT BOUT ↗</Link> : <span className="bout-action unresolved">ROSTER MATCH PENDING</span>}</div>;
        })}
      </article>)}
    </section>
    <div className="home-endnote">SCHEDULED BOUTS MAY CHANGE. MODEL ESTIMATES ARE AVAILABLE ONLY FOR MATCHED CANONICAL FIGHTERS.</div>
  </main>;
}
