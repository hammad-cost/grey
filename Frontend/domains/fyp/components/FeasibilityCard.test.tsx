/**
 * Tests for FeasibilityCard, AcceptedFeasibilityCard and feasibility.ts (Release 0.12).
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import type { FeasibilityView } from "../feasibility";
import { readFeasibility } from "../feasibility";
import { AcceptedFeasibilityCard } from "./AcceptedFeasibilityCard";
import { FeasibilityCard } from "./FeasibilityCard";

const mocks = vi.hoisted(() => ({
  assessFeasibility: vi.fn(),
  acceptFeasibility: vi.fn(),
  state: null as GreyUIState | null,
  isLoading: false,
  error: null as string | null,
}));

vi.mock("@/core/grey-agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/core/grey-agent")>();
  return {
    ...actual,
    useGreyAgent: () => ({ state: mocks.state, isLoading: mocks.isLoading, error: mocks.error }),
    useGreyActions: () => ({ assessFeasibility: mocks.assessFeasibility, acceptFeasibility: mocks.acceptFeasibility }),
  };
});

function makeView(overall = "high"): FeasibilityView {
  return {
    fyp_title: "Explainable alerts for unusual vessel movements",
    dimension_names: { evidence_strength: "Evidence strength", time: "Time" },
    report: {
      id: "f-1",
      status: "draft",
      report: {
        summary: "Realistic if the data work starts early.",
        dimensions: [
          { dimension: "evidence_strength", level: "favourable", finding: "Strong", reason: "2 Tier A sources.", assessed_by: "facts" },
          { dimension: "time", level: "concern", finding: "Tight", reason: "Labelling takes long.", assessed_by: "judgement" },
        ],
        main_risks: [{ risk: "Data preparation takes long", mitigation: "Start with a sample" }],
        overall,
        overall_reason: "1 of 2 dimensions are favourable, 0 moderate and 1 a concern (time).",
      },
    },
  };
}

function reviewState(overrides: Partial<GreyUIState> = {}, view = makeView()): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "feasibility",
    currentStage: "FEASIBILITY",
    status: "awaiting_user",
    allowedActions: ["acceptFeasibility"],
    brainSummary: {},
    eventData: { feasibility: view },
    lastEventType: "feasibility_ready",
    ...overrides,
  };
}

beforeEach(() => {
  for (const action of [mocks.assessFeasibility, mocks.acceptFeasibility]) {
    action.mockReset();
    action.mockResolvedValue({});
  }
  mocks.isLoading = false;
  mocks.error = null;
});

afterEach(cleanup);

describe("readFeasibility", () => {
  it("reads a view and skips broken dimensions", () => {
    const view = makeView();
    view.report!.report.dimensions.push({ dimension: "cost" } as never);
    expect(readFeasibility({ feasibility: view })?.report?.report.dimensions).toHaveLength(2);
    expect(readFeasibility({})).toBeNull();
  });
});

describe("FeasibilityCard", () => {
  it("shows nothing before the check", () => {
    mocks.state = reviewState({ currentStage: "TECHNICAL_PLAN_APPROVED", lastEventType: "technical_plan_approved" });
    expect(render(<FeasibilityCard />).container.innerHTML).toBe("");
  });

  it("shows the live checklist, and Try again after a failure", () => {
    mocks.state = reviewState({ status: "running", allowedActions: [], lastEventType: "feasibility_progress",
      eventData: { steps: [{ id: "checking_facts", label: "Checking the facts", state: "active" }] } });
    render(<FeasibilityCard />);
    expect(screen.getByText("Grey is checking whether your project is feasible…")).toBeTruthy();
    cleanup();
    mocks.state = reviewState({ status: "blocked", allowedActions: ["assessFeasibility"], lastEventType: "feasibility_failed",
      eventData: { message: "Grey couldn't finish the feasibility check right now." } });
    render(<FeasibilityCard />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.assessFeasibility).toHaveBeenCalledOnce();
  });

  it("shows the overall rating, every dimension and the risks", () => {
    mocks.state = reviewState();
    render(<FeasibilityCard />);
    expect(screen.getByLabelText("Overall feasibility rating").textContent).toBe("High");
    const items = within(screen.getByRole("list", { name: "Feasibility dimensions" })).getAllByRole("listitem");
    expect(items[0].textContent).toContain("Evidence strength: Strong");
    expect(items[0].textContent).toContain("from your decisions");
    expect(items[1].textContent).toContain("Grey's judgement");
    expect(screen.getByText(/Start with a sample/)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("warns clearly when feasibility is Low", () => {
    mocks.state = reviewState({}, makeView("low"));
    render(<FeasibilityCard />);
    expect(screen.getByRole("alert").textContent).toContain("hard to finish");
  });

  it("asks to confirm before accepting", () => {
    mocks.state = reviewState();
    render(<FeasibilityCard />);
    fireEvent.click(screen.getByRole("button", { name: "Accept and continue" }));
    expect(mocks.acceptFeasibility).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Yes, accept it" }));
    expect(mocks.acceptFeasibility).toHaveBeenCalledWith("f-1");
  });
});

describe("AcceptedFeasibilityCard", () => {
  it("summarises the accepted report", () => {
    mocks.state = reviewState({ currentStage: "FEASIBILITY_ACCEPTED", lastEventType: "feasibility_accepted" });
    render(<AcceptedFeasibilityCard />);
    expect(screen.getByRole("heading").textContent).toBe("Overall feasibility: High");
    expect(screen.getByText("Data preparation takes long")).toBeTruthy();
  });
});
