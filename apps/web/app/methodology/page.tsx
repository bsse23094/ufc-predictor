import Link from "next/link";

export default function MethodologyPage() {
  return (
    <main className="container" style={{ paddingTop: "2rem", paddingBottom: "4rem" }}>
      <h1>Methodology</h1>
      <section className="card" style={{ padding: "1.5rem", margin: "1.5rem 0" }}>
        <h2>Pre-fight information only</h2>
        <p>
          Historical features are built from bouts strictly earlier than the target bout.
          The API scores only pairs and dates with an accepted pre-fight materialization;
          it reports unavailable data instead of filling missing features with zero.
        </p>
      </section>
      <section className="card" style={{ padding: "1.5rem", margin: "1.5rem 0" }}>
        <h2>Fighter order symmetry</h2>
        <p>
          The winner runtime scores both fighter orientations and symmetrizes the result.
          Reversing the fighters produces complementary probabilities within the tested tolerance.
        </p>
      </section>
      <section className="card" style={{ padding: "1.5rem", margin: "1.5rem 0" }}>
        <h2>Evaluation and limits</h2>
        <p>
          The local champion bundle includes chronological evaluation and confidence coverage.
          Historical calibration metrics describe that evaluation sample; they do not guarantee
          the observed outcome frequency for a future bout. Method, round, duration, and market
          predictions have no accepted production model.
        </p>
        <Link href="/models">View the model card</Link>
      </section>
      <p className="disclaimer-banner">
        Predictions are uncertain analytical estimates, not guarantees or wagering advice.
      </p>
    </main>
  );
}
