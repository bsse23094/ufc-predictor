import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@ufc-predictor/ui/tokens.css";
import "@/styles/globals.css";
import { AppNav } from "@/components/layout/AppNav";
import { AppFooter } from "@/components/layout/AppFooter";
import { QueryProvider } from "@/components/providers/QueryProvider";

export const metadata: Metadata = {
  title: "UFC Predictor | Leakage-Free Pre-Fight Analytics",
  description: "Reproducible, research-grade UFC fight outcome predictive engine. Calibrated probabilities, never betting advice.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        <QueryProvider>
          <AppNav />
          <main id="main-content" style={{ flex: 1, paddingBottom: "4rem" }}>
            {children}
          </main>
          <AppFooter />
        </QueryProvider>
      </body>
    </html>
  );
}
