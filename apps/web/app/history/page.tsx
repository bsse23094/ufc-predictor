"use client";

import { useState } from "react";
import Link from "next/link";
import { useFights } from "@/lib/query/hooks";
import { CardSkeleton } from "@/components/layout/Skeleton";
import { ErrorState } from "@/components/layout/ErrorState";
import { EmptyState } from "@/components/layout/EmptyState";

const DIVISIONS = [
  "All Divisions",
  "Flyweight",
  "Bantamweight",
  "Featherweight",
  "Lightweight",
  "Welterweight",
  "Middleweight",
  "Light Heavyweight",
  "Heavyweight",
];

export default function HistoryPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedDivision, setSelectedDivision] = useState("All Divisions");
  const [limit, setLimit] = useState(30);

  const divisionParam = selectedDivision === "All Divisions" ? undefined : selectedDivision;
  const { data, isLoading, isError, error, refetch } = useFights(divisionParam, limit);

  const bouts = data?.items || [];

  const filteredBouts = bouts.filter((b) => {
    if (!searchTerm.trim()) return true;
    const q = searchTerm.toLowerCase();
    const fA = (b.fighter_a_name || b.participants?.[0]?.display_name || "").toLowerCase();
    const fB = (b.fighter_b_name || b.participants?.[1]?.display_name || "").toLowerCase();
    const ev = (b.event_name || "").toLowerCase();
    const div = (b.weight_class || b.division_code || "").toLowerCase();
    const winner = (b.winner_name || "").toLowerCase();
    return fA.includes(q) || fB.includes(q) || ev.includes(q) || div.includes(q) || winner.includes(q);
  });

  return (
    <div className="container" style={{ paddingTop: "2rem", paddingBottom: "4rem" }}>
      {/* Header */}
      <div style={{ marginBottom: "2rem" }}>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.5rem", flexWrap: "wrap" }}>
          <span className="badge badge-blue">POINT-IN-TIME ARCHIVE</span>
          <span className="badge badge-subtle">
            {isLoading ? "QUERYING ARCHIVE..." : `${bouts.length} VERIFIED BOUTS LOADED`}
          </span>
          <span className="badge badge-green">AUDITED OUTCOMES</span>
        </div>
        <h1 style={{ fontSize: "2.25rem", fontWeight: 900, color: "#fff", letterSpacing: "-0.02em" }}>
          Historical Bout Results &amp; Archives
        </h1>
        <p style={{ color: "var(--color-text-secondary)", fontSize: "1rem" }}>
          Browse verified pre-fight outcomes and examine actual finish methods, scheduled rounds, and winner records across UFC history.
        </p>
      </div>

      {/* Controls: Search and Division Filters */}
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem", marginBottom: "2rem" }}>
        <div style={{ maxWidth: "28rem" }}>
          <input
            type="search"
            className="input"
            placeholder="Search by fighter, event, or division..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{ width: "100%", padding: "0.625rem 0.875rem" }}
            aria-label="Filter historical bouts"
          />
        </div>

        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            overflowX: "auto",
            paddingBottom: "0.5rem",
            scrollbarWidth: "none",
          }}
        >
          {DIVISIONS.map((div) => {
            const isSelected = selectedDivision === div;
            return (
              <button
                key={div}
                onClick={() => setSelectedDivision(div)}
                style={{
                  padding: "0.375rem 0.875rem",
                  borderRadius: "9999px",
                  fontSize: "0.8125rem",
                  fontWeight: 600,
                  whiteSpace: "nowrap",
                  border: isSelected ? "1px solid var(--color-primary, #e11d48)" : "1px solid rgba(255, 255, 255, 0.1)",
                  backgroundColor: isSelected ? "rgba(225, 29, 72, 0.2)" : "rgba(255, 255, 255, 0.04)",
                  color: isSelected ? "#fff" : "var(--color-text-secondary, #94a3b8)",
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
              >
                {div}
              </button>
            );
          })}
        </div>
      </div>

      {/* Error state */}
      {isError && (
        <ErrorState
          title="Could not load fight history"
          message={error instanceof Error ? error.message : "Failed to fetch historical bout records from API."}
          onRetry={() => refetch()}
        />
      )}

      {/* Loading state */}
      {isLoading && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginBottom: "2rem" }}>
          <CardSkeleton height="65px" />
          <CardSkeleton height="65px" />
          <CardSkeleton height="65px" />
          <CardSkeleton height="65px" />
          <CardSkeleton height="65px" />
        </div>
      )}

      {/* Zero results */}
      {!isLoading && !isError && filteredBouts.length === 0 && (
        <EmptyState
          title="No bouts match your criteria"
          message="No historical fights were found matching the selected query or division filter."
          actionText="Clear Filter"
          onAction={() => {
            setSearchTerm("");
            setSelectedDivision("All Divisions");
          }}
        />
      )}

      {/* History Table */}
      {!isLoading && filteredBouts.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: "2rem" }}>
          <div style={{ overflowX: "auto" }}>
            <table className="tott-table" aria-label="Historical fight outcomes">
              <thead>
                <tr style={{ background: "rgba(255, 255, 255, 0.03)", fontSize: "0.75rem", color: "var(--color-text-muted, #64748b)" }}>
                  <th style={{ textAlign: "left", paddingLeft: "1.25rem", paddingBlock: "0.85rem" }}>Date</th>
                  <th style={{ textAlign: "left" }}>Matchup (Corner 1 vs. Corner 2)</th>
                  <th style={{ textAlign: "left" }}>Actual Victor</th>
                  <th style={{ textAlign: "left" }}>Finish Method</th>
                  <th style={{ textAlign: "center" }}>Rounds</th>
                  <th style={{ textAlign: "center", paddingRight: "1.25rem" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredBouts.map((bout, idx: number) => {
                  const pA = bout.participants?.[0];
                  const pB = bout.participants?.[1];

                  const fAId = bout.fighter_a_id || pA?.fighter_id || `fa-${idx}`;
                  const fAName = bout.fighter_a_name || pA?.display_name || "Fighter A";
                  const fBId = bout.fighter_b_id || pB?.fighter_id || `fb-${idx}`;
                  const fBName = bout.fighter_b_name || pB?.display_name || "Fighter B";

                  const winnerId = bout.winner_id || bout.result?.winner_fighter_id;
                  const isAWin = winnerId === fAId;
                  const isBWin = winnerId === fBId;
                  const winnerName = bout.winner_name || (isAWin ? fAName : isBWin ? fBName : (bout.result?.outcome_type === "draw" ? "Draw" : "Unavailable"));

                  const dateStr = bout.date || bout.fight_date || "Past";
                  const div = bout.weight_class || bout.division_code || "UFC Bout";
                  const methodStr = bout.method || bout.result?.canonical_method_code || bout.result?.source_method_label || "Unavailable";

                  return (
                    <tr key={bout.id || bout.fight_id || idx} style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.04)" }}>
                      <td style={{ paddingLeft: "1.25rem", paddingBlock: "1rem" }}>
                        <div className="num" style={{ fontSize: "0.8125rem", color: "var(--color-text-secondary)" }}>
                          {dateStr}
                        </div>
                        <span className="badge badge-subtle" style={{ fontSize: "0.6875rem", marginTop: "4px" }}>
                          {div}
                        </span>
                      </td>

                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                          <Link
                            href={`/fighters/${encodeURIComponent(fAId)}`}
                            style={{
                              fontWeight: 700,
                              color: isAWin ? "#22c55e" : "var(--color-fighter-a)",
                              textDecoration: "none",
                              fontSize: "0.9375rem",
                            }}
                          >
                            {fAName}
                          </Link>
                          <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>vs</span>
                          <Link
                            href={`/fighters/${encodeURIComponent(fBId)}`}
                            style={{
                              fontWeight: 700,
                              color: isBWin ? "#22c55e" : "var(--color-fighter-b)",
                              textDecoration: "none",
                              fontSize: "0.9375rem",
                            }}
                          >
                            {fBName}
                          </Link>
                        </div>
                      </td>

                      <td>
                        <div style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
                          <span style={{ color: "#22c55e", fontWeight: 800 }}>🏆</span>
                          <strong style={{ color: "#fff", fontSize: "0.9375rem" }}>
                            {winnerName}
                          </strong>
                        </div>
                      </td>

                      <td>
                        <span
                          className="badge"
                          style={{
                            backgroundColor: methodStr.includes("KO")
                              ? "rgba(239, 68, 68, 0.15)"
                              : methodStr.includes("Sub")
                              ? "rgba(56, 189, 248, 0.15)"
                              : "rgba(255, 255, 255, 0.05)",
                            color: methodStr.includes("KO")
                              ? "#f87171"
                              : methodStr.includes("Sub")
                              ? "#38bdf8"
                              : "var(--color-text-secondary)",
                            border: "1px solid rgba(255, 255, 255, 0.08)",
                          }}
                        >
                          {methodStr}
                        </span>
                      </td>

                      <td className="num" style={{ textAlign: "center", color: "var(--color-text-muted)", fontSize: "0.8125rem" }}>
                        {bout.scheduled_rounds || 3} Rnds
                      </td>

                      <td style={{ textAlign: "center", paddingRight: "1.25rem" }}>
                        <div style={{ display: "inline-flex", gap: "0.4rem" }}>
                          <Link
                            href={`/simulator?fighter_a=${encodeURIComponent(fAId)}&fighter_b=${encodeURIComponent(fBId)}`}
                            className="btn btn-secondary"
                            style={{ fontSize: "0.6875rem", padding: "0.25rem 0.55rem" }}
                            title="Simulate this matchup"
                          >
                            ⚡ Sim
                          </Link>
                          <Link
                            href={`/compare?fighter_a=${encodeURIComponent(fAId)}&fighter_b=${encodeURIComponent(fBId)}`}
                            className="btn btn-secondary"
                            style={{ fontSize: "0.6875rem", padding: "0.25rem 0.55rem" }}
                            title="Head-to-head comparison"
                          >
                            ⚔ Compare
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Load More Button */}
      {data?.has_more && (
        <div style={{ display: "flex", justifyContent: "center", marginBottom: "2rem" }}>
          <button
            onClick={() => setLimit((prev) => prev + 25)}
            className="btn btn-secondary"
            style={{ padding: "0.625rem 2rem", fontSize: "0.875rem", fontWeight: 700 }}
          >
            Load More Historical Bouts
          </button>
        </div>
      )}
    </div>
  );
}
