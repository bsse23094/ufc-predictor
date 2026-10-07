"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
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

// Events Hooks
export function useUpcomingEvent() {
  return useQuery<EventDetail>({
    queryKey: ["events", "upcoming"],
    queryFn: () => api.getUpcomingEvent(),
    staleTime: 60 * 1000,
  });
}

export function useEvents(status?: string, limit = 20, cursor?: string) {
  return useQuery<Page<EventDetail>>({
    queryKey: ["events", "list", { status, limit, cursor }],
    queryFn: () => api.getEvents(status, limit, cursor),
    staleTime: 60 * 1000,
  });
}

export function useEvent(id: string) {
  return useQuery<EventDetail>({
    queryKey: ["events", "detail", id],
    queryFn: () => api.getEvent(id),
    enabled: Boolean(id),
    staleTime: 120 * 1000,
  });
}

// Fighters Hooks
export function useDivisionStandouts() {
  return useQuery<DivisionStandoutsResponse>({
    queryKey: ["fighters", "division-standouts"],
    queryFn: () => api.getDivisionStandouts(),
    staleTime: 60 * 60 * 1000,
  });
}

export function useFighters(query = "", division?: string, limit = 25, cursor?: string) {
  return useQuery<Page<FighterSummary>>({
    queryKey: ["fighters", "list", { query, division, limit, cursor }],
    queryFn: () => api.getFighters(query, division, limit, cursor),
    staleTime: 120 * 1000,
  });
}

export function useFighter(id: string) {
  return useQuery<FighterDetail>({
    queryKey: ["fighters", "detail", id],
    queryFn: () => api.getFighter(id),
    enabled: Boolean(id),
    staleTime: 300 * 1000,
  });
}

export function useFighterHistory(id: string, limit = 25, cursor?: string) {
  return useQuery<Page<FightSummary>>({
    queryKey: ["fighters", "history", id, { limit, cursor }],
    queryFn: () => api.getFighterHistory(id, limit, cursor),
    enabled: Boolean(id),
    staleTime: 300 * 1000,
  });
}

// Fights Hooks
export function useFights(division?: string, limit = 25, cursor?: string) {
  return useQuery<Page<FightSummary>>({
    queryKey: ["fights", "list", { division, limit, cursor }],
    queryFn: () => api.getFights(division, limit, cursor),
    staleTime: 120 * 1000,
  });
}

export function useFight(id: string) {
  return useQuery<FightSummary>({
    queryKey: ["fights", "detail", id],
    queryFn: () => api.getFight(id),
    enabled: Boolean(id),
    staleTime: 300 * 1000,
  });
}

// Predictions Hooks
export function usePrediction(
  fighter_a_id: string,
  fighter_b_id: string,
  target_fight_date?: string,
  scheduled_rounds = 3,
  mode = "pure",
  enabled = true
) {
  return useQuery<MatchupPrediction>({
    queryKey: ["predictions", "matchup", { fighter_a_id, fighter_b_id, target_fight_date, scheduled_rounds, mode }],
    queryFn: () => api.predictMatchup(fighter_a_id, fighter_b_id, target_fight_date, scheduled_rounds, mode),
    enabled: Boolean(fighter_a_id && fighter_b_id && fighter_a_id !== fighter_b_id && enabled),
    staleTime: 600 * 1000,
  });
}

export function useFightPredictions(fight_id: string) {
  return useQuery<Page<unknown>>({
    queryKey: ["predictions", "fight", fight_id],
    queryFn: () => api.getFightPredictions(fight_id),
    enabled: Boolean(fight_id),
    staleTime: 300 * 1000,
  });
}

// Simulation Hooks
export function useCounterfactual(
  fighter_a_id: string,
  fighter_b_id: string,
  adjustments: Record<string, number>,
  target_fight_date?: string,
  enabled = true
) {
  return useQuery<CounterfactualResult>({
    queryKey: ["simulations", "counterfactual", { fighter_a_id, fighter_b_id, adjustments, target_fight_date }],
    queryFn: () => api.runCounterfactual(fighter_a_id, fighter_b_id, adjustments, target_fight_date),
    enabled: Boolean(fighter_a_id && fighter_b_id && fighter_a_id !== fighter_b_id && enabled),
    staleTime: 300 * 1000,
  });
}

export function useMonteCarlo(
  fighter_a_id: string,
  fighter_b_id: string,
  iterations = 10000,
  scheduled_rounds = 3,
  seed = 42,
  target_fight_date?: string,
  enabled = true
) {
  return useQuery<MonteCarloResult>({
    queryKey: ["simulations", "monte-carlo", { fighter_a_id, fighter_b_id, iterations, scheduled_rounds, seed, target_fight_date }],
    queryFn: () => api.runMonteCarlo(fighter_a_id, fighter_b_id, iterations, scheduled_rounds, seed, target_fight_date),
    enabled: Boolean(fighter_a_id && fighter_b_id && fighter_a_id !== fighter_b_id && enabled),
    staleTime: 300 * 1000,
  });
}

// Similarity Hooks
export function useSimilarMatchups(fighter_a_id: string, fighter_b_id: string, limit = 5, enabled = true) {
  return useQuery<SimilarMatchup[]>({
    queryKey: ["similarity", "matchups", { fighter_a_id, fighter_b_id, limit }],
    queryFn: () => api.getSimilarMatchups(fighter_a_id, fighter_b_id, limit),
    enabled: Boolean(fighter_a_id && fighter_b_id && fighter_a_id !== fighter_b_id && enabled),
    staleTime: 300 * 1000,
  });
}

// Explanation Hooks
export function useExplanation(fighter_a_id: string, fighter_b_id: string, target_fight_date?: string, enabled = true) {
  return useQuery<ExplanationResult>({
    queryKey: ["explanations", { fighter_a_id, fighter_b_id, target_fight_date }],
    queryFn: () => api.getExplanation(fighter_a_id, fighter_b_id, target_fight_date),
    enabled: Boolean(fighter_a_id && fighter_b_id && fighter_a_id !== fighter_b_id && enabled),
    staleTime: 600 * 1000,
  });
}

// Models & Governance Hooks
export function useModels() {
  return useQuery<PublicModelCard[]>({
    queryKey: ["models", "list"],
    queryFn: () => api.getModels(),
    staleTime: 300 * 1000,
  });
}

export function useModelMetrics(model_id: string) {
  return useQuery<ModelEvaluation>({
    queryKey: ["models", "metrics", model_id],
    queryFn: () => api.getModelMetrics(model_id),
    enabled: Boolean(model_id),
    staleTime: 600 * 1000,
  });
}

export function useFreshness() {
  return useQuery<DataFreshnessResponse>({
    queryKey: ["data", "freshness"],
    queryFn: () => api.getFreshness(),
    staleTime: 60 * 1000,
  });
}
