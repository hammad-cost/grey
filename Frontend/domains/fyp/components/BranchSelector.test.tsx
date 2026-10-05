/**
 * Tests for BranchSelector.
 *
 * The Grey adapter (@/core/grey-agent) is replaced with a fake, so each test
 * can set the exact UI state it needs and check which action was called.
 * No backend is needed.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { BranchSelector } from "./BranchSelector";

// vi.hoisted makes these available inside the vi.mock factory below.
const mocks = vi.hoisted(() => ({
  selectBranch: vi.fn(),
  state: null as GreyUIState | null,
  isLoading: false,
}));

vi.mock("@/core/grey-agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/core/grey-agent")>();
  return {
    ...actual,
    useGreyAgent: () => ({ state: mocks.state, isLoading: mocks.isLoading, error: null }),
    useGreyActions: () => ({
      startProject: vi.fn(),
      selectIndustry: vi.fn(),
      selectBranch: mocks.selectBranch,
    }),
  };
});

/** The UI state right after the backend's "industry_saved" event. */
function branchStageState(overrides: Partial<GreyUIState> = {}): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "discovery",
    currentStage: "BRANCH_SELECTION",
    status: "awaiting_user",
    allowedActions: ["selectBranch", "askGrey"],
    brainSummary: { industry: "Finance", industryStatus: "approved" },
    eventData: {
      industry: "Finance",
      available_branches: ["Banking", "Insurance", "Fraud Detection"],
    },
    ...overrides,
  };
}

beforeEach(() => {
  mocks.selectBranch.mockReset();
  mocks.selectBranch.mockResolvedValue(undefined);
  mocks.state = branchStageState();
  mocks.isLoading = false;
});

afterEach(cleanup);

describe("BranchSelector", () => {
  it("asks about the chosen industry and shows one card per branch from the backend event", () => {
    render(<BranchSelector />);

    expect(screen.getByRole("heading").textContent).toBe(
      "Which branch of Finance do you want to focus on?"
    );
    const cards = screen.getAllByRole("button");
    expect(cards.map((card) => card.textContent)).toEqual([
      "Banking",
      "Insurance",
      "Fraud Detection",
    ]);
  });

  it("calls selectBranch with the clicked branch", () => {
    render(<BranchSelector />);

    fireEvent.click(screen.getByRole("button", { name: "Fraud Detection" }));

    expect(mocks.selectBranch).toHaveBeenCalledTimes(1);
    expect(mocks.selectBranch).toHaveBeenCalledWith("Fraud Detection");
  });

  it("renders nothing when selectBranch is not an allowed action", () => {
    mocks.state = branchStageState({
      currentStage: "INDUSTRY_SELECTION",
      allowedActions: ["selectIndustry", "askGrey"],
    });

    const { container } = render(<BranchSelector />);

    expect(container.innerHTML).toBe("");
  });

  it("disables the cards while Grey is busy, so a choice can't be sent twice", () => {
    mocks.isLoading = true;
    render(<BranchSelector />);

    const banking = screen.getByRole("button", { name: "Banking" }) as HTMLButtonElement;
    expect(banking.disabled).toBe(true);

    fireEvent.click(banking);
    expect(mocks.selectBranch).not.toHaveBeenCalled();
  });

  it("ignores anything in the branch list that is not text", () => {
    mocks.state = branchStageState({
      eventData: { available_branches: ["RegTech", 7, undefined] },
    });

    render(<BranchSelector />);

    expect(screen.getAllByRole("button").map((card) => card.textContent)).toEqual(["RegTech"]);
  });

  it("does not crash when the action fails (the adapter shows the error)", async () => {
    mocks.selectBranch.mockRejectedValue(new Error("Backend unavailable"));
    render(<BranchSelector />);

    fireEvent.click(screen.getByRole("button", { name: "Banking" }));
    // Let the rejected promise settle; an unhandled rejection would fail the test run.
    await Promise.resolve();

    expect(mocks.selectBranch).toHaveBeenCalledWith("Banking");
  });
});
