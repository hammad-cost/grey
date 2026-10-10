/**
 * Tests for TechnologyPlanCard, ApprovedTechnologyCard and technology.ts (Release 0.10).
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import type { TechnologyView } from "../technology";
import { readTechnology } from "../technology";
import { ApprovedTechnologyCard } from "./ApprovedTechnologyCard";
import { TechnologyPlanCard } from "./TechnologyPlanCard";

const mocks = vi.hoisted(() => ({
  planTechnology: vi.fn(),
  replanTechnology: vi.fn(),
  approveTechnology: vi.fn(),
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
      planTechnology: mocks.planTechnology,
      replanTechnology: mocks.replanTechnology,
      approveTechnology: mocks.approveTechnology,
    }),
  };
});

function makeTechnology(overrides: Partial<TechnologyView> = {}): TechnologyView {
  return {
    fyp_title: "Explainable alerts for unusual vessel movements",
    uses_ai: true,
    plan: {
      id: "t-1",
      status: "draft",
      plan: {
        summary: "A small web app with a trained model.",
        stack: [
          { area: "frontend", choice: "React", reason: "One interactive dashboard is the main need." },
          { area: "ai_ml", choice: "PyTorch", reason: "It supports fine-tuning." },
        ],
        hardware: [
          { kind: "normal_laptop", name: "A normal laptop", purpose: "Build and demo", essential: true, cost: "none", alternative: null },
          { kind: "cloud_gpu", name: "Cloud GPU", purpose: "Faster training", essential: false, cost: "high", alternative: "Google Colab" },
        ],
      },
      replans_used: 0,
    },
    replans_left: 2,
    max_replans: 2,
    can_replan: true,
    ...overrides,
  };
}

function reviewState(overrides: Partial<GreyUIState> = {}, view = makeTechnology()): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "technology_plan",
    currentStage: "TECHNOLOGY_PLAN",
    status: "awaiting_user",
    allowedActions: ["approveTechnology", "replanTechnology"],
    brainSummary: {},
    eventData: { technology: view },
    lastEventType: "technology_plan_ready",
    ...overrides,
  };
}

beforeEach(() => {
  for (const action of [mocks.planTechnology, mocks.replanTechnology, mocks.approveTechnology]) {
    action.mockReset();
    action.mockResolvedValue({});
  }
  mocks.isLoading = false;
  mocks.error = null;
});

afterEach(cleanup);

describe("readTechnology", () => {
  it("reads a view and skips broken items", () => {
    const view = makeTechnology();
    view.plan!.plan.stack.push({ area: "backend" } as never);
    const read = readTechnology({ technology: view });
    expect(read?.plan?.plan.stack).toHaveLength(2);
    expect(read?.plan?.plan.hardware[1].alternative).toBe("Google Colab");
    expect(readTechnology({})).toBeNull();
  });
});

describe("TechnologyPlanCard", () => {
  it("shows nothing before planning", () => {
    mocks.state = reviewState({ lastEventType: "models_approved", currentStage: "MODELS_APPROVED" });
    expect(render(<TechnologyPlanCard />).container.innerHTML).toBe("");
  });

  it("shows the live checklist while Grey works", () => {
    mocks.state = reviewState({
      status: "running", allowedActions: [], lastEventType: "technology_plan_progress",
      eventData: { steps: [{ id: "planning_technology", label: "Choosing a focused technology stack", state: "active" }] },
    });
    render(<TechnologyPlanCard />);
    expect(screen.getByText("Grey is planning your technology…")).toBeTruthy();
  });

  it("offers Try again after a failure", () => {
    mocks.state = reviewState({
      status: "blocked", allowedActions: ["planTechnology"], lastEventType: "technology_plan_failed",
      eventData: { message: "Grey couldn't finish the technology plan right now." },
    });
    render(<TechnologyPlanCard />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.planTechnology).toHaveBeenCalledOnce();
  });

  it("shows each decision with its reason, and the hardware", () => {
    mocks.state = reviewState();
    render(<TechnologyPlanCard />);
    const stack = screen.getByLabelText("Technology stack");
    expect(within(stack).getByText("React")).toBeTruthy();
    expect(within(stack).getByText("One interactive dashboard is the main need.")).toBeTruthy();
    const hardware = screen.getByRole("list", { name: "Hardware" });
    expect(within(hardware).getByText(/Essential · Free \/ already owned/)).toBeTruthy();
    expect(within(hardware).getByText(/Nice to have · High cost/)).toBeTruthy();
    expect(within(hardware).getByText("Alternative: Google Colab")).toBeTruthy();
  });

  it("asks for a simpler plan while re-plans are left", () => {
    mocks.state = reviewState();
    render(<TechnologyPlanCard />);
    expect(screen.getByText("2 of 2 re-plans left.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Make it simpler / cheaper" }));
    expect(mocks.replanTechnology).toHaveBeenCalledWith("simpler");
  });

  it("hides the re-plan button when none are left", () => {
    mocks.state = reviewState({ allowedActions: ["approveTechnology"] }, makeTechnology({ can_replan: false, replans_left: 0 }));
    render(<TechnologyPlanCard />);
    expect(screen.queryByRole("button", { name: "Make it simpler / cheaper" })).toBeNull();
  });

  it("asks to confirm before approving", () => {
    mocks.state = reviewState();
    render(<TechnologyPlanCard />);
    fireEvent.click(screen.getByRole("button", { name: "Approve technology plan" }));
    expect(mocks.approveTechnology).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Yes, approve it" }));
    expect(mocks.approveTechnology).toHaveBeenCalledWith("t-1");
  });

  it("keeps the review after a failed re-plan", () => {
    mocks.state = reviewState({
      lastEventType: "technology_plan_failed",
      eventData: { technology: makeTechnology(), message: "Grey couldn't make a simpler plan right now." },
    });
    render(<TechnologyPlanCard />);
    expect(screen.getByRole("status").textContent).toBe("Grey couldn't make a simpler plan right now.");
  });
});

describe("ApprovedTechnologyCard", () => {
  it("summarises the approved plan", () => {
    mocks.state = reviewState({ currentStage: "TECHNOLOGY_APPROVED", lastEventType: "technology_approved" });
    render(<ApprovedTechnologyCard />);
    expect(screen.getByText("Frontend: React")).toBeTruthy();
    expect(screen.getByText("Hardware: A normal laptop")).toBeTruthy();
    expect(screen.queryByText("Hardware: Cloud GPU")).toBeNull();
  });
});
