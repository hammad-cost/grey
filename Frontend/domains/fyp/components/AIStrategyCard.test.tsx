/**
 * Tests for AIStrategyCard — the AI necessity check, re-checks with a
 * preference, and approving the AI strategy (Release 0.7).
 *
 * The Grey adapter is replaced with a fake, so each test sets the exact UI
 * state it needs and checks which action was called. No backend is needed.
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { makeAIStrategy, NO_AI_STRATEGY } from "../testAIStrategy";
import { AIStrategyCard } from "./AIStrategyCard";

const mocks = vi.hoisted(() => ({
  checkAINeed: vi.fn(),
  recheckAIStrategy: vi.fn(),
  approveAIStrategy: vi.fn(),
  state: null as GreyUIState | null,
  isLoading: false,
  error: null as string | null,
}));

vi.mock("@/core/grey-agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/core/grey-agent")>();
  return {
    ...actual,
    useGreyAgent: () => ({ state: mocks.state, isLoading: mocks.isLoading, error: mocks.error }),
    useGreyActions: () => ({
      checkAINeed: mocks.checkAINeed,
      recheckAIStrategy: mocks.recheckAIStrategy,
      approveAIStrategy: mocks.approveAIStrategy,
    }),
  };
});

/** The UI state right after the backend's "ai_strategy_ready" event. */
function reviewState(overrides: Partial<GreyUIState> = {}, view = makeAIStrategy()): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "ai_strategy",
    currentStage: "AI_STRATEGY",
    status: "awaiting_user",
    allowedActions: ["approveAIStrategy", "recheckAIStrategy"],
    brainSummary: { industry: "Defense", branch: "Navy" },
    eventData: { ai_strategy: view },
    lastEventType: "ai_strategy_ready",
    ...overrides,
  };
}

function runningState(recheck = false): GreyUIState {
  return reviewState({
    currentStage: recheck ? "AI_STRATEGY" : "SCOPE_APPROVED",
    status: "running",
    allowedActions: [],
    lastEventType: "ai_strategy_progress",
    eventData: {
      recheck,
      label: "Checking the answer against your approved scope",
      steps: [
        { id: "checking_ai_need", label: "Checking whether your project really needs AI", state: "done" },
        { id: "checking_answer", label: "Checking the answer against your approved scope", state: "active" },
        { id: "saving_ai_strategy", label: "Saving it to your Project Brain", state: "pending" },
      ],
    },
  });
}

beforeEach(() => {
  for (const action of [mocks.checkAINeed, mocks.recheckAIStrategy, mocks.approveAIStrategy]) {
    action.mockReset();
    action.mockResolvedValue({});
  }
  mocks.isLoading = false;
  mocks.error = null;
});

afterEach(cleanup);

describe("AIStrategyCard", () => {
  it("shows the live checklist while Grey checks", () => {
    mocks.state = runningState();
    render(<AIStrategyCard />);

    expect(screen.getByRole("heading", { name: /checking whether your project needs AI/ })).toBeTruthy();
    const steps = within(screen.getByRole("list", { name: "AI check steps" })).getAllByRole("listitem");
    expect(steps.map((s) => s.getAttribute("data-state"))).toEqual(["done", "active", "pending"]);
  });

  it("says it is checking again during a re-check", () => {
    mocks.state = runningState(true);
    render(<AIStrategyCard />);
    expect(screen.getByRole("heading", { name: "Grey is checking again…" })).toBeTruthy();
  });

  it("offers Try again when the first check failed", () => {
    mocks.state = reviewState({
      currentStage: "SCOPE_APPROVED",
      status: "blocked",
      allowedActions: ["checkAINeed"],
      lastEventType: "ai_strategy_failed",
      eventData: { message: "Grey couldn't finish checking. Your approved scope is safe." },
    });
    render(<AIStrategyCard />);

    expect(screen.getByText(/Your approved scope is safe/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.checkAINeed).toHaveBeenCalledOnce();
  });

  it("shows the verdict, the no-AI alternative and the AI plan", () => {
    mocks.state = reviewState();
    render(<AIStrategyCard />);

    expect(screen.getByRole("heading", { name: "Traditional machine learning is enough" })).toBeTruthy();
    expect(screen.getByText(/hard to describe with fixed rules/)).toBeTruthy();
    expect(screen.getByText(/Speed and route limits could flag some tracks/)).toBeTruthy();
    expect(screen.getByText("Anomaly detection")).toBeTruthy();
    expect(screen.getByText("Train a model")).toBeTruthy();
    expect(screen.getByText("Hybrid approach")).toBeTruthy();
    expect(within(screen.getByRole("list", { name: "Parts that need no AI" })).getAllByRole("listitem"))
      .toHaveLength(2);
  });

  it("shows no AI plan when the project doesn't need AI", () => {
    mocks.state = reviewState({ allowedActions: ["approveAIStrategy"] }, makeAIStrategy({}, NO_AI_STRATEGY));
    render(<AIStrategyCard />);

    expect(screen.getByRole("heading", { name: "A rule-based approach is better" })).toBeTruthy();
    expect(screen.queryByText("AI / ML strategy")).toBeNull();
    expect(screen.queryByRole("button", { name: /without AI/ })).toBeNull();     // nothing to re-check
  });

  it("re-checks with the chosen preference", () => {
    mocks.state = reviewState();
    render(<AIStrategyCard />);

    expect(screen.getByText(/2 of 2 re-checks left/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Can I do this without AI?" }));
    expect(mocks.recheckAIStrategy).toHaveBeenCalledWith("without_ai");
    fireEvent.click(screen.getByRole("button", { name: "Use a ready-made model instead" }));
    expect(mocks.recheckAIStrategy).toHaveBeenCalledWith("existing_model");
  });

  it("only offers the re-checks the backend allows", () => {
    mocks.state = reviewState({}, makeAIStrategy({ available_rechecks: ["without_ai"], rechecks_left: 1 }));
    render(<AIStrategyCard />);

    expect(screen.getByRole("button", { name: "Can I do this without AI?" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Use a ready-made model instead" })).toBeNull();
    expect(screen.getByText(/1 of 2 re-checks left/)).toBeTruthy();
  });

  it("keeps the review after a failed re-check and shows the message", () => {
    mocks.state = reviewState({
      lastEventType: "ai_strategy_failed",
      eventData: { ai_strategy: makeAIStrategy(), message: "Grey couldn't check again right now." },
    });
    render(<AIStrategyCard />);

    expect(screen.getByRole("status").textContent).toBe("Grey couldn't check again right now.");
    expect(screen.getByRole("button", { name: "Approve AI strategy" })).toBeTruthy();
  });

  it("asks to confirm before approving", () => {
    mocks.state = reviewState();
    render(<AIStrategyCard />);

    fireEvent.click(screen.getByRole("button", { name: "Approve AI strategy" }));
    expect(mocks.approveAIStrategy).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Can I do this without AI?" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Yes, approve it" }));
    expect(mocks.approveAIStrategy).toHaveBeenCalledWith("ai-1");
  });

  it("can cancel the confirmation", () => {
    mocks.state = reviewState();
    render(<AIStrategyCard />);

    fireEvent.click(screen.getByRole("button", { name: "Approve AI strategy" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocks.approveAIStrategy).not.toHaveBeenCalled();
  });

  it("shows nothing for other events or after approval", () => {
    mocks.state = reviewState({ lastEventType: "scope_approved" });
    expect(render(<AIStrategyCard />).container.innerHTML).toBe("");
    cleanup();
    mocks.state = reviewState({ currentStage: "AI_STRATEGY_APPROVED" });
    expect(render(<AIStrategyCard />).container.innerHTML).toBe("");
  });
});
