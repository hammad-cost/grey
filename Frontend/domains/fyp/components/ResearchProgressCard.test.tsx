/**
 * Tests for ResearchProgressCard.
 *
 * The Grey adapter (@/core/grey-agent) is replaced with a fake, so each test
 * can set the exact UI state it needs and check which action was called.
 * No backend is needed.
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { ResearchProgressCard } from "./ResearchProgressCard";

// vi.hoisted makes these available inside the vi.mock factory below.
const mocks = vi.hoisted(() => ({
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
    useGreyActions: () => ({
      startProject: vi.fn(),
      selectIndustry: vi.fn(),
      selectBranch: vi.fn(),
      startResearch: mocks.startResearch,
    }),
  };
});

const STEPS = [
  { id: "organizations", label: "Identifying relevant organizations", state: "done" },
  { id: "official_sources", label: "Reviewing authoritative sources", state: "active" },
  { id: "storing", label: "Saving evidence to your Project Brain", state: "pending" },
];

/** The UI state right after the backend's "branch_saved" event. */
function researchState(overrides: Partial<GreyUIState> = {}): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "discovery",
    currentStage: "EVIDENCE_RESEARCH",
    status: "awaiting_user",
    allowedActions: ["startResearch"],
    brainSummary: { industry: "Defense", branch: "Navy" },
    eventData: { industry: "Defense", branch: "Navy" },
    ...overrides,
  };
}

/** The UI state while research is streaming. */
function runningState(): GreyUIState {
  return researchState({
    status: "running",
    allowedActions: [],
    eventData: { steps: STEPS, sources_found: 4, high_quality_sources: 2 },
  });
}

beforeEach(() => {
  mocks.startResearch.mockReset();
  mocks.startResearch.mockResolvedValue(undefined);
  mocks.state = researchState();
  mocks.isLoading = false;
  mocks.error = null;
});

afterEach(cleanup);

describe("ResearchProgressCard", () => {
  it("shows nothing outside the EVIDENCE_RESEARCH stage", () => {
    mocks.state = researchState({ currentStage: "BRANCH_SELECTION" });
    const { container } = render(<ResearchProgressCard />);
    expect(container.innerHTML).toBe("");
  });

  it("offers to start research for the chosen industry and branch", () => {
    render(<ResearchProgressCard />);

    expect(screen.getByText("Grey is ready to research evidence")).toBeTruthy();
    expect(screen.getByText("Defense")).toBeTruthy();
    expect(screen.getByText("Navy")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Start research" }));
    expect(mocks.startResearch).toHaveBeenCalledTimes(1);
  });

  it("has no start button when the backend doesn't allow startResearch", () => {
    mocks.state = researchState({ allowedActions: [] });
    render(<ResearchProgressCard />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the live checklist and counts while running, with no button", () => {
    mocks.state = runningState();
    mocks.isLoading = true;
    render(<ResearchProgressCard />);

    const items = within(screen.getByRole("list", { name: "Research steps" })).getAllByRole("listitem");
    expect(items.map((item) => item.getAttribute("data-state"))).toEqual(["done", "active", "pending"]);
    expect(items[1].textContent).toContain("Reviewing authoritative sources");
    expect(screen.getByText("4 sources found • 2 high-quality sources")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the evidence summary when research is complete", () => {
    mocks.state = researchState({
      status: "complete",
      allowedActions: [],
      eventData: {
        steps: STEPS.map((s) => ({ ...s, state: "done" })),
        summary: { total_sources: 13, high_quality_count: 7, by_tier: { A: 7, B: 4, C: 2 } },
      },
    });
    render(<ResearchProgressCard />);

    expect(screen.getByText("Research complete")).toBeTruthy();
    expect(screen.getByText("13 sources")).toBeTruthy();
    expect(screen.getByText(/Tier A: 7 · Tier B: 4 · Tier C: 2/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the safe failure message and lets the student try again", () => {
    mocks.state = researchState({
      status: "blocked",
      allowedActions: ["startResearch"],
      eventData: { steps: STEPS, message: "Grey couldn't finish researching right now." },
    });
    render(<ResearchProgressCard />);

    expect(screen.getByText("Research could not be completed")).toBeTruthy();
    expect(screen.getByText("Grey couldn't finish researching right now.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.startResearch).toHaveBeenCalledTimes(1);
  });

  it("lets the student try again if the connection dropped mid-research", () => {
    mocks.state = runningState();
    mocks.isLoading = false;
    mocks.error = "The connection to Grey was lost during research. Please try again.";
    render(<ResearchProgressCard />);

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.startResearch).toHaveBeenCalledTimes(1);
  });

  it("describes the six research steps before starting", () => {
    render(<ResearchProgressCard />);
    expect(screen.getByText(/discover startups working in this branch and confirm them on their own websites/)).toBeTruthy();
  });

  it("shows what was found, by type, when research is complete", () => {
    mocks.state = researchState({
      status: "complete",
      allowedActions: [],
      eventData: {
        steps: STEPS.map((s) => ({ ...s, state: "done" })),
        summary: {
          total_sources: 12, high_quality_count: 7, by_tier: { A: 7, B: 3, C: 2 },
          startups_confirmed: 3,
          by_category: { organizations: 5, news: 1, official_sources: 3, research: 2, datasets: 0 },
        },
      },
    });
    render(<ResearchProgressCard />);

    // Only kinds that were found are listed; "1" is singular.
    expect(screen.getByText("3 startups confirmed · 1 news article · 3 government sources · 2 research papers")).toBeTruthy();
  });
});
