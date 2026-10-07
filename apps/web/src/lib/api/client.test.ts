import { describe, expect, it, vi, beforeEach } from "vitest";
import { api } from "./client";

describe("Web API Client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("getHealth calls /health endpoint", async () => {
    const mockHealth = { status: "ok", version: "0.1.0", release_sha: "test" };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => mockHealth,
    } as Response);

    const result = await api.getHealth();
    expect(result.status).toBe("ok");
  });

  it("predictMatchup normalizes probability payload", async () => {
    const mockMatchup = {
      fighter_a_id: "fa",
      fighter_b_id: "fb",
      fighter_a_win_probability: 0.65,
      fighter_b_win_probability: 0.35,
      method_probabilities: { ko_tko: 0.3, submission: 0.2, decision: 0.5 },
      round_distribution: { round_1: 0.3, round_2: 0.3, round_3: 0.4 },
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => mockMatchup,
    } as Response);

    const res = await api.predictMatchup("fa", "fb");
    expect(res.fighter_a_id).toBe("fa");
    expect(res.fighter_a_win_prob).toBe(0.65);
    expect(res.fighter_b_win_prob).toBe(0.35);
  });

  it("throws descriptive error on HTTP failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      status: 404,
    } as Response);

    await expect(api.getFighter("missing")).rejects.toThrow("HTTP error 404");
  });

  it("does not use unmatched live schedule names as model IDs", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        event_id: "sportsdataio:1",
        event_name: "UFC Test",
        event_date: "2026-11-01",
        bouts: [{
          bout_id: "sportsdataio:2",
          fighter_a: { fighter_id: "", display_name: "New Fighter" },
          fighter_b: { fighter_id: "canonical-2", display_name: "Known Fighter" },
        }],
      }),
    } as Response);
    const card = await api.getUpcomingEvent();
    expect(card.bouts[0].fighter_a_id).toBe("");
    expect(card.bouts[0].fighter_b_id).toBe("canonical-2");
  });
});
