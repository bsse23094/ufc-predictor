import Link from "next/link";

export function AppFooter() {
  return <footer className="arena-footer">
    <div className="container">
      <div className="arena-footer-main">
        <div className="arena-footer-statement"><span className="section-index">THE ANALYSIS CONTINUES /</span><strong>EVERY FIGHT<br />STARTS <em>BEFORE</em><br />THE BELL.</strong><p>Historical, point-in-time UFC winner estimates. Built for research and exploration.</p></div>
        <div className="arena-footer-links"><div><span>EXPLORE</span><Link href="/">Predict</Link><Link href="/simulator">Simulator</Link><Link href="/events">Upcoming card</Link><Link href="/fighters">Fighters</Link></div><div><span>THE DATA</span><Link href="/models">Model card</Link><Link href="/methodology">Methodology</Link><Link href="/data-transparency">Data audit</Link><Link href="/history">Fight archive</Link></div></div>
      </div>
      <div className="arena-footer-bottom"><span>© {new Date().getFullYear()} UFC PREDICTOR</span><span>WINNER MARKET ONLY / ESTIMATES ARE NOT CERTAINTIES</span><Link href="#main-content">BACK TO TOP ↑</Link></div>
    </div>
  </footer>;
}
