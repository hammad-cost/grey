/**
 * Tests for ApprovedAIStrategyCard — the end of Release 0.7.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { makeAIStrategy, NO_AI_STRATEGY } from "../testAIStrategy";
import { ApprovedAIStrategyCard } from "./ApprovedAIStrategyCard";

const mocks = vi.hoisted(() => ({ state: null as GreyUIState | null }));

vi.mock("@/core/grey-agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/core/grey-agent")>();
  return { ...actual, useGreyAgent: () => ({ state: mocks.state, isLoading: false, error: null }) };
});

function approvedState(overrides: Partial<GreyUIState> = {}, view = makeAIStrategy()): GreyUIState {
  view.strategy = { ...view.strategy!, status: "approved" };
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "ai_strategy",
    currentStage: "AI_STRATEGY_APPROVED",
    status: "complete",
    allowedActions: [],
    brainSummary: { fypTitle: "Explainable alerts for unusual vessel movements", aiNecessity: "traditional_ml" },
    eventData: { ai_strategy: { ...view, available_rechecks: [] } },
    lastEventType: "ai_strategy_approved",
    ...overrides,
  };
}

afterEach(cleanup);

describe("ApprovedAIStrategyCard", () => {
  it("summarises the approved AI strategy", () => {
    mocks.state = approvedState();
    render(<ApprovedAIStrategyCard />);

    expect(screen.getByRole("heading", { name: "Explainable alerts for unusual vessel movements" })).toBeTruthy();
    expect(screen.getByText("Traditional machine learning is enough")).toBeTruthy();
    const summary = within(screen.getByRole("list", { name: "AI strategy summary" })).getAllByRole("listitem");
    expect(summary.map((item) => item.textContent)).toEqual([
      "AI task: Anomaly detection", "Main approach: Train a model", "Fallback: Hybrid approach",
    ]);
    expect(screen.queryAllByRole("button")).toHaveLength(0);           // nothing left to decide here
  });

  it("shows only the verdict for a project without AI", () => {
    mocks.state = approvedState({}, makeAIStrategy({}, NO_AI_STRATEGY));
    render(<ApprovedAIStrategyCard />);

    expect(screen.getByText("A rule-based approach is better")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "AI strategy summary" })).toBeNull();
  });

  it("falls back to the Brain summary", () => {
    mocks.state = approvedState({ eventData: {} });
    render(<ApprovedAIStrategyCard />);
    expect(screen.getByRole("heading", { name: "Explainable alerts for unusual vessel movements" })).toBeTruthy();
    expect(screen.getByText("Traditional machine learning is enough")).toBeTruthy();
  });

  it("shows nothing before approval", () => {
    mocks.state = approvedState({ currentStage: "AI_STRATEGY" });
    expect(render(<ApprovedAIStrategyCard />).container.innerHTML).toBe("");
  });
});
