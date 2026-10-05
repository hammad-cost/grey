/**
 * Tests for IndustrySelector.
 *
 * The Grey adapter (@/core/grey-agent) is replaced with a fake, so each test
 * can set the exact UI state it needs and check which action was called.
 * No backend is needed.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { IndustrySelector } from "./IndustrySelector";

// vi.hoisted makes these available inside the vi.mock factory below.
const mocks = vi.hoisted(() => ({
  selectIndustry: vi.fn(),
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
      selectIndustry: mocks.selectIndustry,
      selectBranch: vi.fn(),
    }),
  };
});

/** The UI state right after the backend's "project_created" event. */
function industryStageState(overrides: Partial<GreyUIState> = {}): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "discovery",
    currentStage: "INDUSTRY_SELECTION",
    status: "awaiting_user",
    allowedActions: ["selectIndustry", "askGrey"],
    eventData: { available_industries: ["Healthcare", "Finance", "Education"] },
    ...overrides,
  };
}

beforeEach(() => {
  mocks.selectIndustry.mockReset();
  mocks.selectIndustry.mockResolvedValue(undefined);
  mocks.state = industryStageState();
  mocks.isLoading = false;
});

afterEach(cleanup);

describe("IndustrySelector", () => {
  it("shows Grey's question and one card per industry from the backend event", () => {
    render(<IndustrySelector />);

    expect(screen.getByText("Which industry do you want to build your FYP for?")).toBeTruthy();
    const cards = screen.getAllByRole("button");
    expect(cards.map((card) => card.textContent)).toEqual(["Healthcare", "Finance", "Education"]);
  });

  it("calls selectIndustry with the clicked industry", () => {
    render(<IndustrySelector />);

    fireEvent.click(screen.getByRole("button", { name: "Finance" }));

    expect(mocks.selectIndustry).toHaveBeenCalledTimes(1);
    expect(mocks.selectIndustry).toHaveBeenCalledWith("Finance");
  });

  it("renders nothing when selectIndustry is not an allowed action", () => {
    mocks.state = industryStageState({
      currentStage: "BRANCH_SELECTION",
      allowedActions: ["selectBranch", "askGrey"],
    });

    const { container } = render(<IndustrySelector />);

    expect(container.innerHTML).toBe("");
  });

  it("disables the cards while Grey is busy, so a choice can't be sent twice", () => {
    mocks.isLoading = true;
    render(<IndustrySelector />);

    const finance = screen.getByRole("button", { name: "Finance" }) as HTMLButtonElement;
    expect(finance.disabled).toBe(true);

    fireEvent.click(finance);
    expect(mocks.selectIndustry).not.toHaveBeenCalled();
  });

  it("ignores anything in the industry list that is not text", () => {
    mocks.state = industryStageState({
      eventData: { available_industries: ["Energy", 42, null] },
    });

    render(<IndustrySelector />);

    expect(screen.getAllByRole("button").map((card) => card.textContent)).toEqual(["Energy"]);
  });

  it("does not crash when the action fails (the adapter shows the error)", async () => {
    mocks.selectIndustry.mockRejectedValue(new Error("Backend unavailable"));
    render(<IndustrySelector />);

    fireEvent.click(screen.getByRole("button", { name: "Finance" }));
    // Let the rejected promise settle; an unhandled rejection would fail the test run.
    await Promise.resolve();

    expect(mocks.selectIndustry).toHaveBeenCalledWith("Finance");
  });
});
