import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@ufc-predictor/ui/tokens.css";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "UFC Predictor",
  description: "Reproducible pre-fight UFC analytics. Not betting advice.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        <header className="site-header">
          <span className="brand">UFC Predictor</span>
          <span className="foundation-label">Foundation milestone</span>
        </header>
        <main id="main-content">{children}</main>
        <footer>
          Predictions will be presented as uncertain analytical estimates, never betting advice.
        </footer>
      </body>
    </html>
  );
}
