/**
 * Tests for ArchitectureCard, ApprovedTechnicalPlanCard and architecture.ts (Release 0.11).
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import type { TechnicalPlanView } from "../architecture";
import { pipelineOrder, readTechnicalPlan } from "../architecture";
import { ApprovedTechnicalPlanCard } from "./ApprovedTechnicalPlanCard";
import { ArchitectureCard } from "./ArchitectureCard";

const mocks = vi.hoisted(() => ({
  designArchitecture: vi.fn(),
  redesignArchitecture: vi.fn(),
  approveTechnicalPlan: vi.fn(),
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
      designArchitecture: mocks.designArchitecture,
      redesignArchitecture: mocks.redesignArchitecture,
      approveTechnicalPlan: mocks.approveTechnicalPlan,
    }),
  };
});

function makePlan(overrides: Partial<TechnicalPlanView> = {}): TechnicalPlanView {
  return {
    fyp_title: "Explainable alerts for unusual vessel movements",
    uses_ai: true,
    ai_task: "anomaly_detection",
    plan: {
      id: "a-1",
      status: "draft",
      plan: {
        summary: "Tracks flow through a model to a dashboard.",
        architecture: {
          // Listed out of order on purpose: the diagram follows the flows.
          components: [
            { id: "c3", name: "Dashboard", kind: "interface", role: "Shows alerts", technology: "React" },
            { id: "c1", name: "AIS dataset", kind: "data_source", role: "Vessel tracks", technology: null },
            { id: "c4", name: "Operator", kind: "user", role: "Reviews alerts", technology: null },
            { id: "c2", name: "Anomaly model", kind: "model", role: "Scores tracks", technology: "PyTorch" },
          ],
          flows: [
            { source: "c1", target: "c2", data: "tracks" },
            { source: "c2", target: "c3", data: "scores" },
            { source: "c3", target: "c4", data: "alerts" },
          ],
        },
        evaluation: {
          metrics: [{ metric: "recall", why: "Missing an unusual track is costly.", goal: "Recall of at least 0.8" }],
          tests: [{ kind: "baseline_comparison", how: "Compare with a threshold rule." }],
          baseline: "A simple threshold rule",
        },
      },
      redesigns_used: 0,
    },
    redesigns_left: 2,
    max_redesigns: 2,
    can_redesign: true,
    ...overrides,
  };
}

function reviewState(overrides: Partial<GreyUIState> = {}, view = makePlan()): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "technical_plan",
    currentStage: "ARCHITECTURE",
    status: "awaiting_user",
    allowedActions: ["approveTechnicalPlan", "redesignArchitecture"],
    brainSummary: {},
    eventData: { technical_plan: view },
    lastEventType: "architecture_ready",
    ...overrides,
  };
}

beforeEach(() => {
  for (const action of [mocks.designArchitecture, mocks.redesignArchitecture, mocks.approveTechnicalPlan]) {
    action.mockReset();
    action.mockResolvedValue({});
  }
  mocks.isLoading = false;
  mocks.error = null;
});

afterEach(cleanup);

describe("architecture.ts", () => {
  it("reads the view and orders the pipeline by its flows", () => {
    const view = readTechnicalPlan({ technical_plan: makePlan() });
    expect(pipelineOrder(view!.plan!.plan).map((c) => c.name)).toEqual([
      "AIS dataset", "Anomaly model", "Dashboard", "Operator",
    ]);
    expect(readTechnicalPlan({})).toBeNull();
  });
});

describe("ArchitectureCard", () => {
  it("shows nothing before designing", () => {
    mocks.state = reviewState({ lastEventType: "technology_approved", currentStage: "TECHNOLOGY_APPROVED" });
    expect(render(<ArchitectureCard />).container.innerHTML).toBe("");
  });

  it("shows the live checklist while Grey works", () => {
    mocks.state = reviewState({
      status: "running", allowedActions: [], lastEventType: "architecture_progress",
      eventData: { steps: [{ id: "designing_architecture", label: "Designing", state: "active" }] },
    });
    render(<ArchitectureCard />);
    expect(screen.getByText("Grey is designing your architecture…")).toBeTruthy();
  });

  it("offers Try again after a failure", () => {
    mocks.state = reviewState({
      status: "blocked", allowedActions: ["designArchitecture"], lastEventType: "architecture_failed",
      eventData: { message: "Grey couldn't finish the architecture right now." },
    });
    render(<ArchitectureCard />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.designArchitecture).toHaveBeenCalledOnce();
  });

  it("draws the pipeline and the evaluation plan", () => {
    mocks.state = reviewState();
    render(<ArchitectureCard />);
    const boxes = within(screen.getByRole("list", { name: "Architecture diagram" })).getAllByRole("listitem");
    expect(boxes.map((b) => b.textContent)).toEqual([
      expect.stringContaining("AIS dataset"),
      expect.stringContaining("Anomaly model"),
      expect.stringContaining("Dashboard"),
      expect.stringContaining("Operator"),
    ]);
    expect(boxes[1].textContent).toContain("PyTorch");
    expect(screen.getByText("AIS dataset → Anomaly model: tracks")).toBeTruthy();
    expect(within(screen.getByRole("list", { name: "Evaluation metrics" })).getByText(/Recall —/)).toBeTruthy();
    expect(screen.getByText("Recall of at least 0.8")).toBeTruthy();
    expect(screen.getByText(/Compare with a threshold rule/)).toBeTruthy();
    expect(screen.getByText("A simple threshold rule")).toBeTruthy();
  });

  it("asks for a simpler architecture and confirms approval", () => {
    mocks.state = reviewState();
    render(<ArchitectureCard />);
    fireEvent.click(screen.getByRole("button", { name: "Make it simpler" }));
    expect(mocks.redesignArchitecture).toHaveBeenCalledWith("simpler");
    fireEvent.click(screen.getByRole("button", { name: "Approve technical plan" }));
    expect(mocks.approveTechnicalPlan).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Yes, approve it" }));
    expect(mocks.approveTechnicalPlan).toHaveBeenCalledWith("a-1");
  });

  it("hides the redesign button when none are left, and keeps the review after a failed redesign", () => {
    mocks.state = reviewState({
      allowedActions: ["approveTechnicalPlan"], lastEventType: "architecture_failed",
      eventData: { technical_plan: makePlan({ can_redesign: false }), message: "Grey couldn't simplify the architecture right now." },
    });
    render(<ArchitectureCard />);
    expect(screen.queryByRole("button", { name: "Make it simpler" })).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("couldn't simplify");
  });
});

describe("ApprovedTechnicalPlanCard", () => {
  it("summarises the approved plan", () => {
    mocks.state = reviewState({ currentStage: "TECHNICAL_PLAN_APPROVED", lastEventType: "technical_plan_approved" });
    render(<ApprovedTechnicalPlanCard />);
    expect(screen.getByText("AIS dataset → Anomaly model → Dashboard → Operator")).toBeTruthy();
    expect(screen.getByText("Measured by: Recall")).toBeTruthy();
  });
});
