/* eslint-disable @typescript-eslint/no-explicit-any -- Legacy API shapes are normalized at this boundary. */
import type {
  CounterfactualResult,
  DataFreshnessResponse,
  DivisionStandoutsResponse,
  EventDetail,
  ExplanationResult,
  FighterDetail,
  FighterSummary,
  FightSummary,
  MatchupPrediction,
  MonteCarloResult,
  ModelEvaluation,
  Page,
  PublicModelCard,
  SimilarMatchup,
} from "@ufc-predictor/shared-types";

// When on server or client, resolve the base URL
function getBaseUrl(): string {
  if (typeof window !== "undefined") {
    // browser: use relative URL so next.config rewrite forwards it
    return "";
  }
  return process.env.API_BASE_URL || "http://127.0.0.1:8000";
}

export async function fetchJson<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const base = getBaseUrl();
  const url = `${base}${endpoint}`;
  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options?.headers || {}),
      },
      next: { revalidate: 30 },
    });
    if (!res.ok) {
      throw new Error(`HTTP error ${res.status} from ${endpoint}`);
    }
    return (await res.json()) as T;
  } catch (err) {
    console.warn(`[API fetchJson] Failed to fetch ${url}:`, err);
    throw err;
  }
}

function normalizeFightSummary(r: any): FightSummary {
  const pA = r.participants?.[0];
  const pB = r.participants?.[1];
  const fAId = pA?.fighter_id || r.fighter_a_id || "";
  const fAName = pA?.display_name || r.fighter_a_name || (fAId ? `Fighter ${fAId.slice(0, 6)}` : "Fighter A");
  const fBId = pB?.fighter_id || r.fighter_b_id || "";
  const fBName = pB?.display_name || r.fighter_b_name || (fBId ? `Fighter ${fBId.slice(0, 6)}` : "Fighter B");

  const winnerFid = r.result?.winner_fighter_id || r.winner_id;
  const isAWin = winnerFid === fAId;
  const isBWin = winnerFid === fBId;
  const winnerName = isAWin ? fAName : isBWin ? fBName : (r.result?.outcome_type === "draw" ? "Draw" : r.result?.outcome_type === "no_contest" ? "No Contest" : null);

  const rawMethod = r.result?.canonical_method_code || r.result?.source_method_label || r.method;
  const cleanMethod = rawMethod ? (rawMethod === "KO/TKO" ? "KO/TKO" : rawMethod.charAt(0).toUpperCase() + rawMethod.slice(1)) : null;

  return {
    id: r.fight_id || r.id || `${fAId}-${fBId}`,
    date: r.fight_date || r.date || "",
    promotion: "UFC",
    event_name: r.event_name || "Event unavailable",
    fighter_a_id: fAId,
    fighter_a_name: fAName,
    fighter_b_id: fBId,
    fighter_b_name: fBName,
    winner_id: winnerFid,
    winner_name: winnerName,
    method: cleanMethod,
    finish_round: r.finish_round ?? null,
    finish_time: r.finish_time ?? null,
    is_title_fight: Boolean(r.is_title_fight),
    weight_class: r.division_code || r.weight_class || "UFC Bout",
    participants: r.participants,
    result: r.result,
  } as any;
}

export const api = {
  async getDivisionStandouts(): Promise<DivisionStandoutsResponse> {
    return fetchJson<DivisionStandoutsResponse>("/api/v1/fighters/standouts");
  },
  // Events
  async getUpcomingEvent(options?: RequestInit): Promise<EventDetail> {
      const data = await fetchJson<any>("/api/v1/events/upcoming", options);
      if (!data || !Array.isArray(data.bouts)) {
        throw new Error("Invalid upcoming event response");
      }
      // Normalize bouts
      const normalizedBouts = data.bouts.map((b: any, idx: number) => {
        const fA = b.fighter_a || {};
        const fB = b.fighter_b || {};
        const fAName = fA.display_name || b.fighter_a_name || "Fighter A";
        const fBName = fB.display_name || b.fighter_b_name || "Fighter B";
        // Never turn a provider display name into a canonical model identifier.
        const fAId = fA.fighter_id ?? b.fighter_a_id ?? "";
        const fBId = fB.fighter_id ?? b.fighter_b_id ?? "";
        const probA = b.probability_a ?? b.fighter_a_win_probability ?? null;
        const probB = b.probability_b ?? b.fighter_b_win_probability ?? null;

        return {
          id: b.bout_id || `bout-${idx}`,
          bout_id: b.bout_id || `bout-${idx}`,
          order: idx + 1,
          bout_order: idx + 1,
          weight_class: b.weight_class || "Open Weight",
          rounds: b.scheduled_rounds || 3,
          scheduled_rounds: b.scheduled_rounds || 3,
          is_title_fight: Boolean(b.is_title_bout),
          is_title_bout: Boolean(b.is_title_bout),
          card_placement: b.card_placement || (idx < 5 ? "main_card" : "prelims"),
          fighter_a_id: fAId,
          fighter_a_name: fAName,
          fighter_b_id: fBId,
          fighter_b_name: fBName,
          fighter_a: fA,
          fighter_b: fB,
          fighter_a_win_prob: probA,
          fighter_b_win_prob: probB,
          probability_a: probA,
          probability_b: probB,
          confidence_score: probA !== null && probB !== null ? Math.max(probA, probB) : null,
          predicted_winner_id: b.predicted_winner_id ?? null,
          confidence_tier: b.confidence_tier || "default",
          model_version: b.model_version ?? null,
          prediction_cutoff: b.prediction_cutoff ?? null,
        };
      });

      return {
        event_id: data.event_id || "upcoming-event",
        event_name: data.event_name || "UFC Fight Night",
        event_date: data.event_date,
        location: data.location ?? null,
        status: data.status || "scheduled",
        source_audit_state: data.source_audit_state,
        bout_count: normalizedBouts.length,
        bouts: normalizedBouts,
      };
  },

  async getEvents(
    status?: string,
    limit = 20,
    cursor?: string,
    options?: RequestInit
  ): Promise<Page<EventDetail>> {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    params.set("limit", limit.toString());
    if (cursor) params.set("cursor", cursor);
      return await fetchJson<Page<EventDetail>>(`/api/v1/events?${params.toString()}`, options);
  },

  async getEvent(id: string, options?: RequestInit): Promise<EventDetail> {
      return await fetchJson<EventDetail>(`/api/v1/events/${id}`, options);
  },

  // Fighters
  async getFighters(
    query = "",
    division?: string,
    limit = 25,
    cursor?: string,
    options?: RequestInit
  ): Promise<Page<FighterSummary>> {
    const params = new URLSearchParams();
    if (query && query.trim().length >= 2) params.set("query", query.trim());
    if (division && division !== "All Divisions") params.set("division", division);
    params.set("limit", limit.toString());
    if (cursor) params.set("cursor", cursor);

      const data = await fetchJson<any>(`/api/v1/fighters?${params.toString()}`, options);
      const items: FighterSummary[] = (data.items || []).map((f: any) => {
        const fid = f.canonical_fighter_id || f.fighter_id || f.id;
        const name = f.canonical_display_name || f.display_name || `${f.first_name || ""} ${f.last_name || ""}`.trim() || fid;
        const nameParts = name.split(" ");
        return {
          id: fid,
          fighter_id: fid,
          display_name: name,
          first_name: f.first_name || nameParts[0] || "",
          last_name: f.last_name || nameParts.slice(1).join(" ") || "",
          nickname: f.nickname || null,
          stance: f.stance || null,
          height_cm: f.height_cm ? Number(f.height_cm) : null,
          reach_cm: f.reach_cm ? Number(f.reach_cm) : null,
          weight_class: f.weight_class || f.division || null,
          division: f.division || f.weight_class || null,
        };
      });

      return {
        items,
        next_cursor: data.next_cursor || null,
        has_more: Boolean(data.has_more),
      };
  },

  async getFighter(id: string, options?: RequestInit): Promise<FighterDetail> {
      const f = await fetchJson<any>(`/api/v1/fighters/${id}`, options);
      const fid = f.fighter_id || f.canonical_fighter_id || f.id || id;
      const name = f.display_name || f.canonical_display_name || `${f.first_name || ""} ${f.last_name || ""}`.trim() || fid;
      const nameParts = name.split(" ");

      return {
        id: fid,
        first_name: f.first_name || nameParts[0] || "",
        last_name: f.last_name || nameParts.slice(1).join(" ") || "",
        nickname: f.nickname || null,
        stance: f.stance || null,
        height_cm: f.height_cm ? Number(f.height_cm) : null,
        reach_cm: f.reach_cm ? Number(f.reach_cm) : null,
        weight_class: f.weight_class || f.division || null,
        division: f.division || f.weight_class || null,
        display_name: name,
        stats: f.stats ?? null,
        bouts: (f.bouts || []).map(normalizeFightSummary),
      };
  },

  async getFighterHistory(
    id: string,
    limit = 25,
    cursor?: string,
    options?: RequestInit
  ): Promise<Page<FightSummary>> {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (cursor) params.set("cursor", cursor);
      const data = await fetchJson<any>(`/api/v1/fighters/${id}/history?${params.toString()}`, options);
      const items = (data.items || []).map(normalizeFightSummary);
      return {
        items,
        next_cursor: data.next_cursor || null,
        has_more: Boolean(data.has_more),
      };
  },

  // Fights
  async getFights(
    division?: string,
    limit = 25,
    cursor?: string,
    options?: RequestInit
  ): Promise<Page<FightSummary>> {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (division && division !== "All Divisions") params.set("division", division);
    if (cursor) params.set("cursor", cursor);
      const data = await fetchJson<any>(`/api/v1/fights?${params.toString()}`, options);
      const items = (data.items || []).map(normalizeFightSummary);
      return {
        items,
        next_cursor: data.next_cursor || null,
        has_more: Boolean(data.has_more),
      };
  },

  async getFight(id: string, options?: RequestInit): Promise<FightSummary> {
    const raw = await fetchJson<any>(`/api/v1/fights/${id}`, options);
    return normalizeFightSummary(raw);
  },

  // Predictions
  async predictMatchup(
    fighter_a_id: string,
    fighter_b_id: string,
    target_fight_date?: string,
    scheduled_rounds = 3,
    mode = "pure",
    options?: RequestInit
  ): Promise<MatchupPrediction> {
    const body: Record<string, any> = {
      fighter_a_id,
      fighter_b_id,
      scheduled_rounds,
      mode,
    };
    if (target_fight_date) body.target_fight_date = target_fight_date;

      const data = await fetchJson<any>("/api/v1/predictions/matchup", {
        method: "POST",
        body: JSON.stringify(body),
        ...options,
      });

      const probA = data.fighter_a_win_probability;
      const probB = data.fighter_b_win_probability;
      if (!Number.isFinite(probA) || !Number.isFinite(probB) || Math.abs(probA + probB - 1) > 1e-6) {
        throw new Error("Invalid model probability response");
      }
      const methods = data.method_probabilities;

      return {
        fighter_a_id: data.fighter_a_id || fighter_a_id,
        fighter_b_id: data.fighter_b_id || fighter_b_id,
        fighter_a_name: data.fighter_a_name || data.fighter_a_id || "Fighter A",
        fighter_b_name: data.fighter_b_name || data.fighter_b_id || "Fighter B",
        fighter_a_win_prob: probA,
        fighter_b_win_prob: probB,
        confidence_score: data.confidence_score ?? Math.max(probA, probB),
        model_version: data.model_version,
        generated_at: data.prediction_timestamp,
        prediction_cutoff: data.history_cutoff_date ?? "",
        limitations: data.limitations ?? [],
        method_probabilities: methods ? {
          fighter_a_ko: methods.ko_tko * probA,
          fighter_a_sub: methods.submission * probA,
          fighter_a_dec: methods.decision * probA,
          fighter_b_ko: methods.ko_tko * probB,
          fighter_b_sub: methods.submission * probB,
          fighter_b_dec: methods.decision * probB,
        } : undefined,
        round_probabilities: data.round_distribution ?? undefined,
        duration_expected_seconds: data.duration_expected_seconds ?? undefined,
      };
  },

  async getFightPredictions(fight_id: string, options?: RequestInit): Promise<Page<unknown>> {
    return fetchJson<Page<unknown>>(`/api/v1/predictions/fights/${fight_id}`, options);
  },

  // Simulations
  async runCounterfactual(
    fighter_a_id: string,
    fighter_b_id: string,
    adjustments: Record<string, number>,
    target_fight_date?: string,
    options?: RequestInit
  ): Promise<CounterfactualResult> {
      return await fetchJson<CounterfactualResult>("/api/v1/simulations/counterfactual", {
        method: "POST",
        body: JSON.stringify({
          fighter_a_id,
          fighter_b_id,
          adjustments,
          target_fight_date,
        }),
        ...options,
      });
  },

  async runMonteCarlo(
    fighter_a_id: string,
    fighter_b_id: string,
    iterations = 10000,
    scheduled_rounds = 3,
    seed = 42,
    target_fight_date?: string,
    options?: RequestInit
  ): Promise<MonteCarloResult> {
      const raw = await fetchJson<any>("/api/v1/simulations/monte-carlo", {
        method: "POST",
        body: JSON.stringify({
          fighter_a_id,
          fighter_b_id,
          iterations,
          scheduled_rounds,
          seed,
          target_fight_date,
        }),
        ...options,
      });

      const methods = raw.method_distribution || {};
      let koTko = 0;
      let submission = 0;
      let decision = 0;
      for (const [k, v] of Object.entries(methods)) {
        const val = typeof v === "number" ? v : 0;
        const lower = k.toLowerCase();
        if (lower.includes("ko") || lower.includes("tko")) {
          koTko += val;
        } else if (lower.includes("sub")) {
          submission += val;
        } else if (lower.includes("dec")) {
          decision += val;
        }
      }
      const sumMethods = koTko + submission + decision;
      if (sumMethods > 0) {
        koTko /= sumMethods;
        submission /= sumMethods;
        decision /= sumMethods;
      } else {
        koTko = 0.32;
        submission = 0.20;
        decision = 0.48;
      }

      const rounds = raw.round_distribution || {};
      const winA = raw.simulated_win_rate_a ?? raw.win_probability_a ?? 0.5;
      const winB = raw.simulated_win_rate_b ?? raw.win_probability_b ?? (1 - winA);
      const medianSec = raw.duration_quantiles?.p50 ?? raw.median_duration_seconds ?? 600;
      const meanSec = raw.average_duration_seconds ?? raw.mean_duration_seconds ?? medianSec;

      return {
        fighter_a_id: raw.fighter_a_id || fighter_a_id,
        fighter_b_id: raw.fighter_b_id || fighter_b_id,
        iterations: raw.iterations ?? iterations,
        win_probability_a: winA,
        win_probability_b: winB,
        method_probabilities: {
          ko_tko: koTko,
          submission,
          decision,
        },
        round_distribution: {
          round_1: rounds["Round 1"] ?? rounds["round_1"] ?? 0.3,
          round_2: rounds["Round 2"] ?? rounds["round_2"] ?? 0.25,
          round_3: rounds["Round 3"] ?? rounds["round_3"] ?? 0.2,
          round_4: rounds["Round 4"] ?? rounds["round_4"] ?? null,
          round_5: rounds["Round 5"] ?? rounds["round_5"] ?? null,
        },
        median_duration_seconds: Math.round(medianSec),
        mean_duration_seconds: Math.round(meanSec),
        seed: raw.seed ?? seed,
      };
  },

  // Similarity
  async getSimilarMatchups(
    fighter_a_id: string,
    fighter_b_id: string,
    limit = 5,
    options?: RequestInit
  ): Promise<SimilarMatchup[]> {
      const params = new URLSearchParams({
        fighter_a_id,
        fighter_b_id,
        limit: limit.toString(),
      });
      const items = await fetchJson<any[]>(`/api/v1/similarity/matchups?${params.toString()}`, options);
      return items.map((m) => ({
        bout_id: m.canonical_bout_id || m.bout_id,
        fighter_a_name: m.fighter_a_name,
        fighter_b_name: m.fighter_b_name,
        date: m.fight_date,
        event_name: m.event_name || "UFC Event",
        similarity_score: m.similarity_score,
        winner_name: m.winner_name,
        method: m.finish_method,
        round: m.finish_round,
      }));
  },

  // Explanations
  async getExplanation(
    fighter_a_id: string,
    fighter_b_id: string,
    target_fight_date?: string,
    options?: RequestInit
  ): Promise<ExplanationResult> {
      const params = new URLSearchParams({ fighter_a_id, fighter_b_id });
      if (target_fight_date) params.set("target_fight_date", target_fight_date);
      return await fetchJson<ExplanationResult>(`/api/v1/explanations?${params.toString()}`, options);
  },

  // Models & Governance
  async getModels(options?: RequestInit): Promise<PublicModelCard[]> {
      return await fetchJson<PublicModelCard[]>("/api/v1/models", options);
  },

  async getModelMetrics(model_id: string, options?: RequestInit): Promise<ModelEvaluation> {
      return await fetchJson<ModelEvaluation>(`/api/v1/models/${model_id}/metrics`, options);
  },

  async getFreshness(options?: RequestInit): Promise<DataFreshnessResponse> {
      return await fetchJson<DataFreshnessResponse>("/api/v1/data/freshness", options);
  },

  // Health & Readiness
  async getHealth(options?: RequestInit): Promise<{ status: string; version: string; release_sha: string }> {
    return fetchJson("/health", options);
  },

  async getReadiness(options?: RequestInit): Promise<{ status: string; environment: string; capabilities: Record<string, string> }> {
    return fetchJson("/readiness", options);
  },
};
