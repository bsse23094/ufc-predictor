"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "PREDICT" },
  { href: "/simulator", label: "SIMULATOR" },
  { href: "/events", label: "FIGHT CARD" },
  { href: "/compare", label: "COMPARE" },
  { href: "/fighters", label: "FIGHTERS" },
  { href: "/history", label: "HISTORY" },
  { href: "/models", label: "MODEL" },
  { href: "/methodology", label: "METHOD" },
];

export function AppNav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  return <header className="arena-header">
    <div className="container arena-nav-inner">
      <Link href="/" className="arena-brand" aria-label="UFC Predictor homepage" onClick={() => setOpen(false)}>
        <span className="arena-brand-mark">UFC</span><span className="arena-brand-name">PREDICTOR<span className="arena-brand-slash">/</span></span>
      </Link>
      <nav className="arena-desktop-nav" aria-label="Main navigation">
        {links.map(({ href, label }) => <Link key={href} href={href} className={`arena-nav-link ${pathname === href || (href === "/fighters" && pathname.startsWith("/fighters/")) ? "is-active" : ""}`}>{label}</Link>)}
      </nav>
      <button type="button" className="arena-mobile-toggle" aria-label={open ? "Close navigation" : "Open navigation"} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "CLOSE ×" : "MENU ☰"}</button>
    </div>
    {open && <nav className="arena-mobile-nav" aria-label="Mobile navigation">{links.map(({ href, label }) => <Link key={href} href={href} onClick={() => setOpen(false)} className={pathname === href ? "is-active" : ""}>{label}<span>↗</span></Link>)}<Link href="/data-transparency" onClick={() => setOpen(false)}>DATA AUDIT <span>↗</span></Link></nav>}
  </header>;
}
