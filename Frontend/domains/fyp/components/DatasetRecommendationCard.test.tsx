/**
 * Tests for DatasetRecommendationCard — the dataset search, re-searches with a
 * preference, and selecting one of the two datasets (Release 0.8).
 *
 * The Grey adapter is replaced with a fake, so each test sets the exact UI
 * state it needs and checks which action was called. No backend is needed.
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { makeDatasets, PUBLIC_DATASET } from "../testDatasets";
import { DatasetRecommendationCard } from "./DatasetRecommendationCard";

const mocks = vi.hoisted(() => ({
  findDatasets: vi.fn(),
  requestDatasetAlternative: vi.fn(),
  selectDataset: vi.fn(),
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
      findDatasets: mocks.findDatasets,
      requestDatasetAlternative: mocks.requestDatasetAlternative,
      selectDataset: mocks.selectDataset,
    }),
  };
});

/** The UI state right after the backend's "dataset_options_ready" event. */
function reviewState(overrides: Partial<GreyUIState> = {}, view = makeDatasets()): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "dataset_discovery",
    currentStage: "DATASET_DISCOVERY",
    status: "awaiting_user",
    allowedActions: ["selectDataset", "requestDatasetAlternative"],
    brainSummary: { industry: "Defense", branch: "Navy" },
    eventData: { datasets: view },
    lastEventType: "dataset_options_ready",
    ...overrides,
  };
}

function runningState(research = false): GreyUIState {
  return reviewState({
    currentStage: research ? "DATASET_DISCOVERY" : "AI_STRATEGY_APPROVED",
    status: "running",
    allowedActions: [],
    lastEventType: "dataset_search_progress",
    eventData: {
      research,
      label: "Choosing the two best options for your project",
      steps: [
        { id: "searching_datasets", label: "Searching dataset sites", state: "done" },
        { id: "choosing_datasets", label: "Choosing the two best options for your project", state: "active" },
        { id: "checking_datasets", label: "Checking each dataset really fits your problem", state: "pending" },
        { id: "saving_datasets", label: "Saving it to your Project Brain", state: "pending" },
      ],
    },
  });
}

beforeEach(() => {
  for (const action of [mocks.findDatasets, mocks.requestDatasetAlternative, mocks.selectDataset]) {
    action.mockReset();
    action.mockResolvedValue({});
  }
  mocks.isLoading = false;
  mocks.error = null;
});

afterEach(cleanup);

describe("DatasetRecommendationCard", () => {
  it("shows nothing before the dataset search starts", () => {
    mocks.state = reviewState({ lastEventType: "ai_strategy_approved", currentStage: "AI_STRATEGY_APPROVED" });
    const { container } = render(<DatasetRecommendationCard />);
    expect(container.firstChild).toBeNull();
  });

  it("shows the live checklist from the backend while Grey works", () => {
    mocks.state = runningState();
    render(<DatasetRecommendationCard />);
    expect(screen.getByText("Grey is looking for data for your project…")).toBeTruthy();
    const steps = within(screen.getByRole("list", { name: "Dataset search steps" })).getAllByRole("listitem");
    expect(steps.map((s) => s.getAttribute("data-state"))).toEqual(["done", "active", "pending", "pending"]);
  });

  it("says when Grey is searching again", () => {
    mocks.state = runningState(true);
    render(<DatasetRecommendationCard />);
    expect(screen.getByText("Grey is searching again…")).toBeTruthy();
  });

  it("offers Try again after a failed first search", () => {
    mocks.state = reviewState({
      status: "blocked",
      allowedActions: ["findDatasets"],
      lastEventType: "dataset_search_failed",
      eventData: { message: "Grey couldn't finish looking for datasets right now." },
    });
    render(<DatasetRecommendationCard />);
    expect(screen.getByText("Grey couldn't finish looking for datasets right now.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.findDatasets).toHaveBeenCalledOnce();
  });

  it("shows both datasets with the details a student needs", () => {
    mocks.state = reviewState();
    render(<DatasetRecommendationCard />);

    expect(screen.getByText("Train and test the track checker.")).toBeTruthy();
    expect(screen.getByText(/Grey looked at 6 dataset pages from 4 searches/)).toBeTruthy();
    const main = screen.getByRole("article", { name: "Grey's main pick" });
    const link = within(main).getByRole("link", { name: PUBLIC_DATASET.name });
    expect(link.getAttribute("href")).toBe(PUBLIC_DATASET.url);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(within(main).getByText(/Public dataset · Kaggle · Good fit/)).toBeTruthy();
    expect(within(main).getByText("CC BY 4.0")).toBeTruthy();
    expect(within(main).getByText("Position, Speed, Heading")).toBeTruthy();
    expect(within(main).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Remove duplicate positions", "Split by vessel", "Coastal waters only",
    ]);

    const alternative = screen.getByRole("article", { name: "Alternative" });
    expect(within(alternative).queryByRole("link")).toBeNull();          // own data has no link
    expect(within(alternative).getByText(/Data you generate · Partial fit/)).toBeTruthy();
    expect(within(alternative).getByText(/Write a small simulator/)).toBeTruthy();
    expect(screen.queryByText("Sample data")).toBeNull();
  });

  it("marks sample (mock) datasets", () => {
    mocks.state = reviewState({}, makeDatasets({}, { ...PUBLIC_DATASET, url: "https://datasets.ml-hub.example/x" }));
    render(<DatasetRecommendationCard />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("asks to confirm before selecting a dataset", () => {
    mocks.state = reviewState();
    render(<DatasetRecommendationCard />);

    const alternative = screen.getByRole("article", { name: "Alternative" });
    fireEvent.click(within(alternative).getByRole("button", { name: "Use this dataset" }));
    expect(mocks.selectDataset).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog").textContent).toContain("Use “Simulated vessel tracks”?");
    expect(screen.queryByRole("button", { name: "Use this dataset" })).toBeNull();   // one choice at a time

    fireEvent.click(screen.getByRole("button", { name: "Yes, use this dataset" }));
    expect(mocks.selectDataset).toHaveBeenCalledWith("plan-1", "alternative");
  });

  it("can cancel the confirmation", () => {
    mocks.state = reviewState();
    render(<DatasetRecommendationCard />);
    fireEvent.click(screen.getAllByRole("button", { name: "Use this dataset" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocks.selectDataset).not.toHaveBeenCalled();
  });

  it("offers only the re-searches the backend allows, with how many are left", () => {
    mocks.state = reviewState({}, makeDatasets({ available_researches: ["other_options"], researches_left: 1 }));
    render(<DatasetRecommendationCard />);
    expect(screen.getByText("1 of 2 new searches left.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "I'd rather create or collect my own data" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Find other options" }));
    expect(mocks.requestDatasetAlternative).toHaveBeenCalledWith("other_options");
  });

  it("hides re-searches when none are left", () => {
    mocks.state = reviewState({ allowedActions: ["selectDataset"] }, makeDatasets({ available_researches: [] }));
    render(<DatasetRecommendationCard />);
    expect(screen.queryByText(/new searches left/)).toBeNull();
    expect(screen.getAllByRole("button", { name: "Use this dataset" })).toHaveLength(2);
  });

  it("keeps the review after a failed re-search, with the message on top", () => {
    mocks.state = reviewState({
      lastEventType: "dataset_search_failed",
      eventData: { datasets: makeDatasets(), message: "Grey couldn't search again right now." },
    });
    render(<DatasetRecommendationCard />);
    expect(screen.getByRole("status").textContent).toBe("Grey couldn't search again right now.");
    expect(screen.getAllByRole("button", { name: "Use this dataset" })).toHaveLength(2);
  });

  it("disappears once a dataset is selected", () => {
    mocks.state = reviewState({ currentStage: "DATASET_SELECTED", lastEventType: "dataset_selected" });
    const { container } = render(<DatasetRecommendationCard />);
    expect(container.firstChild).toBeNull();
  });
});
