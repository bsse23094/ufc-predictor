"use client";

import { use } from "react";
import Link from "next/link";
import { useFighter, useFighterHistory } from "@/lib/query/hooks";
import { Skeleton, CardSkeleton } from "@/components/layout/Skeleton";
import { ErrorState } from "@/components/layout/ErrorState";
import { EmptyState } from "@/components/layout/EmptyState";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function FighterDetailPage({ params }: PageProps) {
  const resolvedParams = use(params);
  const fighterId = resolvedParams.id;

  const {
    data: fighter,
    isLoading: isFighterLoading,
    isError: isFighterError,
    error: fighterError,
    refetch: refetchFighter,
  } = useFighter(fighterId);

  const {
    data: historyData,
  } = useFighterHistory(fighterId, 50);

  const displayName =
    fighter?.display_name ||
    (fighter ? `${fighter.first_name || ""} ${fighter.last_name || ""}`.trim() : null) ||
    fighterId.replace("f-", "").replace(/-/g, " ");

  const bouts = fighter?.bouts?.length ? fighter.bouts : (historyData?.items || []);
  const stats = fighter?.stats;

  if (isFighterLoading) {
    return (
      <div className="container" style={{ paddingTop: "2rem" }}>
        <Skeleton width="180px" height="24px" style={{ marginBottom: "1rem" }} />
        <Skeleton width="60%" height="48px" style={{ marginBottom: "1.5rem" }} />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1rem", marginBottom: "2rem" }}>
          <CardSkeleton height="100px" />
          <CardSkeleton height="100px" />
          <CardSkeleton height="100px" />
          <CardSkeleton height="100px" />
        </div>
      </div>
    );
  }

  if (isFighterError) {
    return (
      <div className="container" style={{ paddingTop: "2rem" }}>
        <Link href="/fighters" className="btn btn-secondary" style={{ marginBottom: "1.5rem", display: "inline-block" }}>
          ← Back to Fighter Directory
        </Link>
        <ErrorState
          title="Fighter Not Found"
          message={fighterError instanceof Error ? fighterError.message : `Unable to locate fighter profile for "${fighterId}".`}
          onRetry={() => refetchFighter()}
        />
      </div>
    );
  }

  return (
    <div className="container" style={{ paddingTop: "2rem", paddingBottom: "4rem" }}>
      {/* Back button */}
      <div style={{ marginBottom: "1.25rem" }}>
        <Link
          href="/fighters"
          style={{
            fontSize: "0.875rem",
            color: "var(--color-text-secondary)",
            textDecoration: "none",
            display: "inline-flex",
            alignItems: "center",
            gap: "0.25rem",
          }}
        >
          ← Back to Fighter Directory
        </Link>
      </div>

      {/* Hero Fighter Profile Banner */}
      <div
        className="card"
        style={{
          marginBottom: "2rem",
          padding: "2rem",
          background: "linear-gradient(135deg, rgba(225, 29, 72, 0.1) 0%, rgba(15, 23, 42, 0.95) 100%)",
          border: "1px solid rgba(255, 255, 255, 0.12)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "1.25rem" }}>
          <div>
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.5rem", flexWrap: "wrap" }}>
              <span className="badge badge-danger">{fighter?.division || fighter?.weight_class || "UFC ATHLETE"}</span>
              {fighter?.nickname && (
                <span className="badge badge-subtle">&quot;{fighter.nickname}&quot;</span>
              )}
              <span className="badge badge-blue">CANONICAL PROFILE</span>
            </div>

            <h1 style={{ fontSize: "2.5rem", fontWeight: 900, color: "#fff", letterSpacing: "-0.02em", margin: "0.25rem 0" }}>
              {displayName}
            </h1>

            <div style={{ display: "flex", gap: "1.5rem", alignItems: "center", marginTop: "0.75rem", flexWrap: "wrap", fontSize: "0.9375rem" }}>
              <div>
                <span style={{ color: "var(--color-text-muted)" }}>Record: </span>
                <strong style={{ color: "#fff" }}>
                  {stats ? `${stats.wins}W – ${stats.losses}L${stats.draws ? ` – ${stats.draws}D` : ""}` : "Record unavailable"}
                </strong>
              </div>
              <div>
                <span style={{ color: "var(--color-text-muted)" }}>Stance: </span>
                <strong style={{ color: "#fff" }}>{fighter?.stance || "Unavailable"}</strong>
              </div>
              <div>
                <span style={{ color: "var(--color-text-muted)" }}>Height: </span>
                <strong style={{ color: "#fff" }}>{fighter?.height_cm ? `${fighter.height_cm} cm` : "—"}</strong>
              </div>
              <div>
                <span style={{ color: "var(--color-text-muted)" }}>Reach: </span>
                <strong style={{ color: "#fff" }}>{fighter?.reach_cm ? `${fighter.reach_cm} cm` : "—"}</strong>
              </div>
            </div>
          </div>

          {/* Quick Action buttons */}
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <Link
              href={`/compare?fighter_a=${encodeURIComponent(fighterId)}`}
              className="btn btn-secondary"
              style={{ fontWeight: 700 }}
            >
              ⚔ Compare Against...
            </Link>
            <Link
              href={`/simulator?fighter_a=${encodeURIComponent(fighterId)}`}
              className="btn btn-primary"
              style={{ fontWeight: 800 }}
            >
              ⚡ Open in Simulator
            </Link>
          </div>
        </div>

        {/* Career Striking & Grappling Metrics Grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: "1rem",
            marginTop: "1.75rem",
            paddingTop: "1.5rem",
            borderTop: "1px solid rgba(255, 255, 255, 0.1)",
          }}
        >
          <div style={{ padding: "1rem", borderRadius: "8px", backgroundColor: "rgba(255, 255, 255, 0.04)" }}>
            <div style={{ fontSize: "0.75rem", color: "var(--color-text-secondary)", marginBottom: "0.25rem" }}>
              Sig. Strikes Landed / Min
            </div>
            <div className="num" style={{ fontSize: "1.75rem", fontWeight: 800, color: "#fff" }}>
              {stats?.sig_strike_landed_per_min ? stats.sig_strike_landed_per_min.toFixed(2) : "—"}
            </div>
            <div style={{ fontSize: "0.6875rem", color: "var(--color-text-muted)", marginTop: "0.25rem" }}>
              Striking output volume
            </div>
          </div>

          <div style={{ padding: "1rem", borderRadius: "8px", backgroundColor: "rgba(255, 255, 255, 0.04)" }}>
            <div style={{ fontSize: "0.75rem", color: "var(--color-text-secondary)", marginBottom: "0.25rem" }}>
              Striking Accuracy
            </div>
            <div className="num" style={{ fontSize: "1.75rem", fontWeight: 800, color: "#22c55e" }}>
              {stats?.sig_strike_acc ? `${(stats.sig_strike_acc * 100).toFixed(0)}%` : "—"}
            </div>
            <div style={{ fontSize: "0.6875rem", color: "var(--color-text-muted)", marginTop: "0.25rem" }}>
              Connection rate
            </div>
          </div>

          <div style={{ padding: "1rem", borderRadius: "8px", backgroundColor: "rgba(255, 255, 255, 0.04)" }}>
            <div style={{ fontSize: "0.75rem", color: "var(--color-text-secondary)", marginBottom: "0.25rem" }}>
              Striking Defense
            </div>
            <div className="num" style={{ fontSize: "1.75rem", fontWeight: 800, color: "#38bdf8" }}>
              {stats?.sig_strike_def ? `${(stats.sig_strike_def * 100).toFixed(0)}%` : "—"}
            </div>
            <div style={{ fontSize: "0.6875rem", color: "var(--color-text-muted)", marginTop: "0.25rem" }}>
              Strikes evaded
            </div>
          </div>

          <div style={{ padding: "1rem", borderRadius: "8px", backgroundColor: "rgba(255, 255, 255, 0.04)" }}>
            <div style={{ fontSize: "0.75rem", color: "var(--color-text-secondary)", marginBottom: "0.25rem" }}>
              Takedown Defense
            </div>
            <div className="num" style={{ fontSize: "1.75rem", fontWeight: 800, color: "#eab308" }}>
              {stats?.td_def ? `${(stats.td_def * 100).toFixed(0)}%` : "—"}
            </div>
            <div style={{ fontSize: "0.6875rem", color: "var(--color-text-muted)", marginTop: "0.25rem" }}>
              Sprawl efficacy
            </div>
          </div>
        </div>
      </div>

      {/* Fight History Table */}
      <div style={{ marginBottom: "3rem" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" }}>
          <h2 style={{ fontSize: "1.25rem", fontWeight: 800, color: "#fff", margin: 0 }}>
            Fight History &amp; Verified Records
          </h2>
          <span className="badge badge-subtle">{bouts.length} RECORDED BOUTS</span>
        </div>

        {bouts.length === 0 ? (
          <EmptyState
            title="No fight records in catalog"
            message="No historical bouts have been verified yet for this canonical fighter."
          />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {bouts.map((bout, idx: number) => {
              const pA = bout.participants?.[0];
              const pB = bout.participants?.[1];

              const fAId = bout.fighter_a_id || pA?.fighter_id;
              const fAName = bout.fighter_a_name || pA?.display_name || "Fighter A";
              const fBId = bout.fighter_b_id || pB?.fighter_id;
              const fBName = bout.fighter_b_name || pB?.display_name || "Fighter B";

              const winnerId = bout.winner_id || bout.result?.winner_fighter_id;

              const isMeA = fAId === fighterId;
              const isMeB = fBId === fighterId;

              const opponentId = isMeA ? fBId : fAId;
              const opponentName = isMeA ? fBName : fAName;

              const isWin = (winnerId && (winnerId === fighterId || (isMeA && winnerId === fAId) || (isMeB && winnerId === fBId))) ||
                            (bout.result?.outcome_type === "winner" && winnerId === fighterId);
              const isLoss = (winnerId && winnerId !== fighterId && (winnerId === opponentId || winnerId === fAId || winnerId === fBId));

              const resultBadge = isWin ? "badge-green" : isLoss ? "badge-danger" : "badge-subtle";
              const resultText = isWin ? "WIN" : isLoss ? "LOSS" : "DRAW / NC";
              const methodStr = bout.method || bout.result?.canonical_method_code || bout.result?.source_method_label || "Decision";

              return (
                <div
                  key={bout.id || bout.fight_id || idx}
                  className="card"
                  style={{
                    padding: "1rem 1.25rem",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    flexWrap: "wrap",
                    gap: "0.75rem",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                    <span
                      className={`badge ${resultBadge}`}
                      style={{ minWidth: "55px", textAlign: "center", fontWeight: 800 }}
                    >
                      {resultText}
                    </span>

                    <div>
                      <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
                        <span style={{ fontSize: "0.8125rem", color: "var(--color-text-secondary)" }}>vs</span>
                        <Link
                          href={`/fighters/${encodeURIComponent(opponentId || opponentName)}`}
                          style={{ fontWeight: 700, color: "#fff", textDecoration: "none", fontSize: "1rem" }}
                        >
                          {opponentName || "Unknown Opponent"}
                        </Link>
                      </div>

                      <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "2px" }}>
                        {bout.date || bout.fight_date || "Past Bout"} • {bout.weight_class || bout.division_code || "UFC"}
                      </div>
                    </div>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                    <div style={{ textAlign: "right" }}>
                      <span className="badge badge-subtle" style={{ fontSize: "0.75rem" }}>
                        {methodStr}
                      </span>
                    </div>

                    <div style={{ display: "flex", gap: "0.4rem" }}>
                      {opponentId && (
                        <>
                          <Link
                            href={`/simulator?fighter_a=${encodeURIComponent(fighterId)}&fighter_b=${encodeURIComponent(opponentId)}`}
                            className="btn btn-secondary"
                            style={{ fontSize: "0.6875rem", padding: "0.25rem 0.55rem" }}
                            title="Simulate rematch"
                          >
                            ⚡ Sim
                          </Link>
                          <Link
                            href={`/compare?fighter_a=${encodeURIComponent(fighterId)}&fighter_b=${encodeURIComponent(opponentId)}`}
                            className="btn btn-secondary"
                            style={{ fontSize: "0.6875rem", padding: "0.25rem 0.55rem" }}
                            title="Compare athletes"
                          >
                            ⚔ Compare
                          </Link>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
