/**
 * Tests for ModelRecommendationCard and ApprovedModelsCard (Release 0.9).
 * The Grey adapter is replaced with a fake; no backend is needed.
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { readModels } from "../models";
import { FINE_TUNE_MODEL, makeModels } from "../testModels";
import { ApprovedModelsCard } from "./ApprovedModelsCard";
import { ModelRecommendationCard } from "./ModelRecommendationCard";

const mocks = vi.hoisted(() => ({
  findModels: vi.fn(),
  requestOtherModels: vi.fn(),
  approveModels: vi.fn(),
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
      findModels: mocks.findModels,
      requestOtherModels: mocks.requestOtherModels,
      approveModels: mocks.approveModels,
    }),
  };
});

function reviewState(overrides: Partial<GreyUIState> = {}, view = makeModels()): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "model_selection",
    currentStage: "MODEL_SELECTION",
    status: "awaiting_user",
    allowedActions: ["approveModels", "requestOtherModels"],
    brainSummary: {},
    eventData: { models: view },
    lastEventType: "models_ready",
    ...overrides,
  };
}

beforeEach(() => {
  for (const action of [mocks.findModels, mocks.requestOtherModels, mocks.approveModels]) {
    action.mockReset();
    action.mockResolvedValue({});
  }
  mocks.isLoading = false;
  mocks.error = null;
});

afterEach(cleanup);

describe("readModels", () => {
  it("reads a view and drops broken options and unknown re-searches", () => {
    const view = makeModels({ available_researches: ["other_options", "more"] }, [
      FINE_TUNE_MODEL, { kind: "x" } as never,
    ]);
    const read = readModels({ models: view });
    expect(read?.plan?.plan.options).toEqual([FINE_TUNE_MODEL]);
    expect(read?.available_researches).toEqual(["other_options"]);
    expect(readModels({})).toBeNull();
  });
});

describe("ModelRecommendationCard", () => {
  it("shows nothing before the model search", () => {
    mocks.state = reviewState({ lastEventType: "dataset_selected", currentStage: "DATASET_SELECTED" });
    expect(render(<ModelRecommendationCard />).container.innerHTML).toBe("");
  });

  it("shows the live checklist while Grey works", () => {
    mocks.state = reviewState({
      status: "running", allowedActions: [], lastEventType: "model_search_progress",
      eventData: { steps: [{ id: "searching_models", label: "Searching model hubs, code and AI services", state: "active" }] },
    });
    render(<ModelRecommendationCard />);
    expect(screen.getByText("Grey is checking what already exists…")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Model search steps" })).toBeTruthy();
  });

  it("offers Try again after a failed first search", () => {
    mocks.state = reviewState({
      status: "blocked", allowedActions: ["findModels"], lastEventType: "model_search_failed",
      eventData: { message: "Grey couldn't finish looking for models right now." },
    });
    render(<ModelRecommendationCard />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.findModels).toHaveBeenCalledOnce();
  });

  it("shows each option with its link, use and reason", () => {
    mocks.state = reviewState();
    render(<ModelRecommendationCard />);
    expect(screen.getByText("Fine-tune the first model and compare against the code.")).toBeTruthy();
    const panel = screen.getByRole("article", { name: "vessel-track-anomaly" });
    expect(within(panel).getByRole("link").getAttribute("href")).toBe(FINE_TUNE_MODEL.url);
    expect(within(panel).getByText("Fine-tune it")).toBeTruthy();
    expect(within(panel).getByText(/Pretrained model · huggingface.co · for The track checker/)).toBeTruthy();
    expect(screen.getByRole("article", { name: "ais-anomaly" })).toBeTruthy();
    expect(screen.getByText("Grey looked at 7 pages from 4 searches.")).toBeTruthy();
  });

  it("says when nothing ready-made fits", () => {
    mocks.state = reviewState({}, makeModels({}, []));
    render(<ModelRecommendationCard />);
    expect(screen.getByText(/Nothing ready-made fits well/)).toBeTruthy();
  });

  it("shows 'no model needed' for a project without AI", () => {
    const view = makeModels({ available_researches: [] }, []);
    view.plan!.plan = { needs_model: false, summary: "Your approved AI strategy doesn't use AI.", options: [] };
    mocks.state = reviewState({ allowedActions: ["approveModels"] }, view);
    render(<ModelRecommendationCard />);
    expect(screen.getByRole("heading", { name: "No model needed" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Look for other models" })).toBeNull();
  });

  it("asks for other models", () => {
    mocks.state = reviewState();
    render(<ModelRecommendationCard />);
    expect(screen.getByText("2 of 2 new searches left.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Look for other models" }));
    expect(mocks.requestOtherModels).toHaveBeenCalledWith("other_options");
  });

  it("asks to confirm before approving", () => {
    mocks.state = reviewState();
    render(<ModelRecommendationCard />);
    fireEvent.click(screen.getByRole("button", { name: "Approve model plan" }));
    expect(mocks.approveModels).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Yes, approve it" }));
    expect(mocks.approveModels).toHaveBeenCalledWith("m-1");
  });

  it("keeps the review after a failed re-search", () => {
    mocks.state = reviewState({
      lastEventType: "model_search_failed",
      eventData: { models: makeModels(), message: "Grey couldn't search again right now." },
    });
    render(<ModelRecommendationCard />);
    expect(screen.getByRole("status").textContent).toBe("Grey couldn't search again right now.");
  });
});

describe("ApprovedModelsCard", () => {
  it("summarises the approved plan", () => {
    mocks.state = reviewState({ currentStage: "MODELS_APPROVED", lastEventType: "models_approved" });
    render(<ApprovedModelsCard />);
    expect(screen.getByText("vessel-track-anomaly: Fine-tune it")).toBeTruthy();
  });

  it("shows nothing before approval", () => {
    mocks.state = reviewState();
    expect(render(<ApprovedModelsCard />).container.innerHTML).toBe("");
  });
});
