/**
 * Tests for SupervisorReadinessCard, SupervisorReadyCard and supervisorBrief.ts (Release 0.13).
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import type { SupervisorBriefView } from "../supervisorBrief";
import { readSupervisorBrief, summaryAsText } from "../supervisorBrief";
import { SupervisorReadinessCard } from "./SupervisorReadinessCard";
import { SupervisorReadyCard } from "./SupervisorReadyCard";

const mocks = vi.hoisted(() => ({
  prepareSupervisorBrief: vi.fn(),
  confirmSupervisorReady: vi.fn(),
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
      prepareSupervisorBrief: mocks.prepareSupervisorBrief,
      confirmSupervisorReady: mocks.confirmSupervisorReady,
    }),
  };
});

function makeView(attention = 0): SupervisorBriefView {
  return {
    fyp_title: "Explainable alerts for unusual vessel movements",
    ready: attention === 0,
    attention_count: attention,
    brief: {
      id: "b-1",
      status: "draft",
      brief: {
        checks: [
          { check: "problem_clear", question: "Is the problem clear?", status: "pass", detail: "Written down." },
          { check: "evidence_supported", question: "Is the problem supported by evidence?",
            status: attention ? "attention" : "pass", detail: attention ? "Find a primary source." : "2 strong sources." },
        ],
        summary: [
          { label: "Project title", value: "Explainable alerts" },
          { label: "Dataset", value: "AIS tracks (public dataset, Kaggle)" },
        ],
        questions: [{ id: "why_this_problem", question: "Why did you choose this problem?",
                      talking_points: ["Operators review tracks by hand.", "Late detection is costly."] }],
      },
    },
  };
}

function reviewState(overrides: Partial<GreyUIState> = {}, view = makeView()): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "supervisor_readiness",
    currentStage: "SUPERVISOR_READINESS",
    status: "awaiting_user",
    allowedActions: ["confirmSupervisorReady"],
    brainSummary: {},
    eventData: { supervisor_brief: view },
    lastEventType: "supervisor_readiness_ready",
    ...overrides,
  };
}

beforeEach(() => {
  for (const action of [mocks.prepareSupervisorBrief, mocks.confirmSupervisorReady]) {
    action.mockReset();
    action.mockResolvedValue({});
  }
  mocks.isLoading = false;
  mocks.error = null;
});

afterEach(cleanup);

describe("supervisorBrief.ts", () => {
  it("reads the view and turns the summary into text", () => {
    const view = readSupervisorBrief({ supervisor_brief: makeView() });
    expect(view?.brief?.brief.questions[0].talking_points).toHaveLength(2);
    expect(summaryAsText("Title", view!.brief!.brief)).toBe(
      "Title\n\nProject title: Explainable alerts\nDataset: AIS tracks (public dataset, Kaggle)"
    );
    expect(readSupervisorBrief({})).toBeNull();
  });
});

describe("SupervisorReadinessCard", () => {
  it("shows nothing before the brief", () => {
    mocks.state = reviewState({ currentStage: "FEASIBILITY_ACCEPTED", lastEventType: "feasibility_accepted" });
    expect(render(<SupervisorReadinessCard />).container.innerHTML).toBe("");
  });

  it("shows the checklist while Grey works and Try again after a failure", () => {
    mocks.state = reviewState({ status: "running", allowedActions: [], lastEventType: "supervisor_brief_progress",
      eventData: { steps: [{ id: "checking_readiness", label: "Running the checks", state: "active" }] } });
    render(<SupervisorReadinessCard />);
    expect(screen.getByText("Grey is preparing you for your supervisor…")).toBeTruthy();
    cleanup();
    mocks.state = reviewState({ status: "blocked", allowedActions: ["prepareSupervisorBrief"],
      lastEventType: "supervisor_brief_failed", eventData: { message: "Grey couldn't finish your supervisor brief right now." } });
    render(<SupervisorReadinessCard />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.prepareSupervisorBrief).toHaveBeenCalledOnce();
  });

  it("shows the checks, the summary and the questions with talking points", () => {
    mocks.state = reviewState();
    render(<SupervisorReadinessCard />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("You're ready to meet your supervisor");
    const checks = within(screen.getByRole("list", { name: "Readiness checks" })).getAllByRole("listitem");
    expect(checks.map((c) => c.getAttribute("data-status"))).toEqual(["pass", "pass"]);
    expect(screen.getByText("AIS tracks (public dataset, Kaggle)")).toBeTruthy();
    expect(screen.getByText("Why did you choose this problem?")).toBeTruthy();
    expect(screen.getByText("Late detection is costly.")).toBeTruthy();
  });

  it("says how many checks need attention", () => {
    mocks.state = reviewState({}, makeView(1));
    render(<SupervisorReadinessCard />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("1 thing to sort out first");
    fireEvent.click(screen.getByRole("button", { name: "I'm ready for my supervisor" }));
    expect(screen.getByRole("dialog").textContent).toContain("Some checks still need attention");
  });

  it("asks to confirm before confirming", () => {
    mocks.state = reviewState();
    render(<SupervisorReadinessCard />);
    fireEvent.click(screen.getByRole("button", { name: "I'm ready for my supervisor" }));
    expect(mocks.confirmSupervisorReady).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Yes, I'm ready" }));
    expect(mocks.confirmSupervisorReady).toHaveBeenCalledWith("b-1");
  });
});

describe("SupervisorReadyCard", () => {
  it("summarises readiness", () => {
    mocks.state = reviewState({ currentStage: "SUPERVISOR_READY", lastEventType: "supervisor_ready_confirmed" });
    render(<SupervisorReadyCard />);
    expect(screen.getByText("Every readiness check passed.")).toBeTruthy();
  });
});
