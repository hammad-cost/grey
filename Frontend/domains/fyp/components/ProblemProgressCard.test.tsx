/**
 * Tests for ProblemProgressCard (finding problems) and SelectedProblemCard
 * (the chosen problem), plus ResearchProgressCard's short summary once Grey
 * has moved on to problems.
 *
 * The Grey adapter is replaced with a fake. No backend is needed.
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { makeProblem } from "../testProblems";
import { ProblemProgressCard } from "./ProblemProgressCard";
import { ResearchProgressCard } from "./ResearchProgressCard";
import { SelectedProblemCard } from "./SelectedProblemCard";

const mocks = vi.hoisted(() => ({
  extractProblems: vi.fn(),
  startResearch: vi.fn(),
  state: null as GreyUIState | null,
  isLoading: false,
  error: null as string | null,
}));

vi.mock("@/core/grey-agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/core/grey-agent")>();
  return {
    ...actual,
    useGreyAgent: () => ({ state: mocks.state, isLoading: mocks.isLoading, error: mocks.error }),
    useGreyActions: () => ({ extractProblems: mocks.extractProblems, startResearch: mocks.startResearch }),
  };
});

const STEPS = [
  { id: "reviewing_evidence", label: "Reviewing your evidence", state: "done" },
  { id: "identifying_problems", label: "Identifying real problems organizations face", state: "active" },
  { id: "checking_problems", label: "Checking each problem against its sources", state: "pending" },
];

function state(overrides: Partial<GreyUIState> = {}): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "discovery",
    currentStage: "EVIDENCE_RESEARCH",
    status: "running",
    allowedActions: [],
    brainSummary: {
      industry: "Defense", branch: "Navy", researchStatus: "complete",
      evidenceCount: 13, highQualityEvidenceCount: 8,
    },
    eventData: { steps: STEPS, label: "Identifying real problems organizations face" },
    lastEventType: "problem_extraction_progress",
    ...overrides,
  };
}

function failedState(allowed: string[], message: string): GreyUIState {
  return state({
    status: "blocked",
    allowedActions: allowed,
    eventData: { steps: [], message },
    lastEventType: "problem_extraction_failed",
  });
}

beforeEach(() => {
  mocks.extractProblems.mockReset().mockResolvedValue(undefined);
  mocks.startResearch.mockReset().mockResolvedValue(undefined);
  mocks.state = state();
  mocks.isLoading = true;
  mocks.error = null;
});

afterEach(cleanup);

describe("ProblemProgressCard", () => {
  it("shows nothing while research events are still arriving", () => {
    mocks.state = state({ lastEventType: "research_completed" });
    const { container } = render(<ProblemProgressCard />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the live checklist from the backend, with no button while working", () => {
    render(<ProblemProgressCard />);

    const items = within(screen.getByRole("list", { name: "Problem steps" })).getAllByRole("listitem");
    expect(items.map((i) => i.getAttribute("data-state"))).toEqual(["done", "active", "pending"]);
    expect(items[1].textContent).toContain("Identifying real problems organizations face");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("on failure shows the backend's message and lets the student try again", () => {
    mocks.state = failedState(["extractProblems"], "Grey couldn't finish finding problems right now.");
    mocks.isLoading = false;
    render(<ProblemProgressCard />);

    expect(screen.getByText("Problems could not be found")).toBeTruthy();
    expect(screen.getByText("Grey couldn't finish finding problems right now.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.extractProblems).toHaveBeenCalledTimes(1);
  });

  it("when the evidence was too thin, offers to research again", () => {
    mocks.state = failedState(["startResearch"], "Try running the research again.");
    mocks.isLoading = false;
    render(<ProblemProgressCard />);

    fireEvent.click(screen.getByRole("button", { name: "Research again" }));
    expect(mocks.startResearch).toHaveBeenCalledTimes(1);
    expect(mocks.extractProblems).not.toHaveBeenCalled();
  });

  it("offers to try again if the connection dropped mid-stream", () => {
    mocks.isLoading = false;
    mocks.error = "The connection to Grey was lost during finding problems. Please try again.";
    render(<ProblemProgressCard />);

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.extractProblems).toHaveBeenCalledTimes(1);
  });
});

describe("ResearchProgressCard once Grey is finding problems", () => {
  it("shrinks to a one-line research summary with no buttons", () => {
    mocks.state = failedState(["startResearch"], "Try running the research again.");
    mocks.isLoading = false;
    render(<ResearchProgressCard />);

    const card = screen.getByRole("region", { name: "Evidence research" });
    expect(card.textContent).toContain("Research complete");
    expect(card.textContent).toContain("13 sources");
    expect(card.textContent).toContain("8 high-quality");
    expect(within(card).queryByRole("button")).toBeNull();
  });
});

describe("SelectedProblemCard", () => {
  function selectedState(): GreyUIState {
    return state({
      currentStage: "PROBLEM_SELECTED",
      status: "complete",
      eventData: { problem: makeProblem(2) },
      lastEventType: "problem_selected",
      brainSummary: { industry: "Defense", branch: "Navy", selectedProblemTitle: "Problem 2: abnormal vessel movement detection" },
    });
  }

  it("shows nothing before a problem is chosen", () => {
    const { container } = render(<SelectedProblemCard />);
    expect(container.innerHTML).toBe("");
  });

  it("summarises the chosen problem and where it sits", () => {
    mocks.state = selectedState();
    render(<SelectedProblemCard />);

    expect(screen.getByRole("heading", { name: "Problem 2: abnormal vessel movement detection" })).toBeTruthy();
    expect(screen.getByText("Defense")).toBeTruthy();
    expect(screen.getByText("Navy")).toBeTruthy();
    expect(screen.getByText("Flag unusual tracks in public AIS data (2).")).toBeTruthy();
    expect(screen.getByText(/Backed by 2 sources/)).toBeTruthy();
  });
});
