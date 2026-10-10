/**
 * Tests for SelectedDatasetCard — the end of Release 0.8.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { makeDatasets, PUBLIC_DATASET } from "../testDatasets";
import { SelectedDatasetCard } from "./SelectedDatasetCard";

const mocks = vi.hoisted(() => ({ state: null as GreyUIState | null }));

vi.mock("@/core/grey-agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/core/grey-agent")>();
  return { ...actual, useGreyAgent: () => ({ state: mocks.state, isLoading: false, error: null }) };
});

function selectedState(choice: "primary" | "alternative", overrides: Partial<GreyUIState> = {}): GreyUIState {
  const view = makeDatasets();
  view.plan = { ...view.plan!, status: "selected", selected: choice };
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "dataset_discovery",
    currentStage: "DATASET_SELECTED",
    status: "complete",
    allowedActions: [],
    brainSummary: { datasetSelected: "Saved name" },
    eventData: { datasets: view },
    lastEventType: "dataset_selected",
    ...overrides,
  };
}

afterEach(cleanup);

describe("SelectedDatasetCard", () => {
  it("shows nothing before a dataset is selected", () => {
    mocks.state = selectedState("primary", { currentStage: "DATASET_DISCOVERY" });
    const { container } = render(<SelectedDatasetCard />);
    expect(container.firstChild).toBeNull();
  });

  it("summarises a selected public dataset with its link", () => {
    mocks.state = selectedState("primary");
    render(<SelectedDatasetCard />);
    expect(screen.getByRole("link", { name: PUBLIC_DATASET.name }).getAttribute("href")).toBe(PUBLIC_DATASET.url);
    expect(screen.getByText("Public dataset from Kaggle")).toBeTruthy();
    expect(screen.getByText("License: CC BY 4.0")).toBeTruthy();
  });

  it("summarises selected own data with how to get it", () => {
    mocks.state = selectedState("alternative");
    render(<SelectedDatasetCard />);
    expect(screen.getByRole("heading").textContent).toBe("Simulated vessel tracks");
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(/Write a small simulator/)).toBeTruthy();
  });

  it("falls back to the Project Brain when the event has no view", () => {
    mocks.state = selectedState("primary", { eventData: {} });
    render(<SelectedDatasetCard />);
    expect(screen.getByRole("heading").textContent).toBe("Saved name");
  });
});
