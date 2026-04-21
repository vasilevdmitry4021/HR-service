import { afterEach, describe, expect, it } from "vitest";

import {
  clearSearchState,
  HR_SEARCH_STATE_KEY,
  readSearchState,
} from "@/lib/search-state";

describe("search-state analyze progress migration", () => {
  afterEach(() => {
    clearSearchState();
  });

  it("migrates legacy snapshotAnalyzeProgress payload", () => {
    sessionStorage.setItem(
      HR_SEARCH_STATE_KEY,
      JSON.stringify({
        query: "python",
        filters: null,
        results: null,
        activeTab: "all",
        snapshotAnalyzeProgress: {
          status: "running",
          stage: "preparing",
          total: 15,
          processed: 3,
          analyzed: 1,
        },
      }),
    );

    const state = readSearchState();
    expect(state).not.toBeNull();
    expect(state?.snapshotAnalyzeProgress).toEqual({
      status: "running",
      stage: "preparing",
      phase: "enriching",
      total: 15,
      processed: 3,
      analyzed: 1,
      phaseTotal: 15,
      phaseDone: 3,
      enriched: 0,
      progressPercent: 0,
    });
  });

  it("migrates payload without phase and phase counters", () => {
    sessionStorage.setItem(
      HR_SEARCH_STATE_KEY,
      JSON.stringify({
        query: "python",
        filters: null,
        results: null,
        activeTab: "all",
        snapshotAnalyzeProgress: {
          status: "running",
          stage: "running",
          total: 10,
          processed: 4,
          analyzed: 2,
        },
      }),
    );

    const state = readSearchState();
    expect(state).not.toBeNull();
    expect(state?.snapshotAnalyzeProgress).toEqual({
      status: "running",
      stage: "running",
      phase: "analyzing",
      total: 10,
      processed: 4,
      analyzed: 2,
      phaseTotal: 10,
      phaseDone: 4,
      enriched: 0,
      progressPercent: 0,
    });
  });
});
