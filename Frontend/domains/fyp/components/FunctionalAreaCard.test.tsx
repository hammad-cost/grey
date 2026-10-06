/**
 * Tests for FunctionalAreaCard — "Your project area" (Release 0.5).
 *
 * The Grey adapter is replaced with a fake, so each test sets the exact UI state.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { makeFYP } from "../testFYP";
import { FunctionalAreaCard } from "./FunctionalAreaCard";

const mocks = vi.hoisted(() => ({ state: null as GreyUIState | null }));

vi.mock("@/core/grey-agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/core/grey-agent")>();
  return { ...actual, useGreyAgent: () => ({ state: mocks.state, isLoading: false, error: null }) };
});

function areaState(overrides: Partial<GreyUIState> = {}): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "fyp_design",
    currentStage: "FYP_DESIGN",
    status: "awaiting_user",
    allowedActions: [],
    brainSummary: {
      industry: "Defense",
      branch: "Navy",
      functionalArea: "Maritime Surveillance",
      specificArea: "Vessel Behavior Monitoring",
      selectedProblemTitle: "Abnormal vessel movement detection",
    },
    eventData: { fyp: makeFYP() },
    lastEventType: "fyp_direction_ready",
    ...overrides,
  };
}

afterEach(cleanup);

describe("FunctionalAreaCard", () => {
  it("shows the whole path from industry to problem, with the explanation", () => {
    mocks.state = areaState();
    render(<FunctionalAreaCard />);

    for (const text of ["Defense", "Navy", "Maritime Surveillance", "Vessel Behavior Monitoring",
                        "Abnormal vessel movement detection", "The problem is about how ships move."]) {
      expect(screen.getByText(text)).toBeTruthy();
    }
  });

  it("appears as soon as the area is classified, while the design is still running", () => {
    mocks.state = areaState({
      currentStage: "AREA_CLASSIFICATION",
      status: "running",
      lastEventType: "area_classified",
      eventData: { area: makeFYP().area },
    });
    render(<FunctionalAreaCard />);
    expect(screen.getByRole("region", { name: "Your project area" })).toBeTruthy();
    expect(screen.getByText("The problem is about how ships move.")).toBeTruthy();
  });

  it("shows nothing before the area is known or after approval", () => {
    mocks.state = areaState({ currentStage: "PROBLEM_SELECTED", brainSummary: {} });
    expect(render(<FunctionalAreaCard />).container.innerHTML).toBe("");
    cleanup();
    mocks.state = areaState({ currentStage: "APPROVED_FYP" });
    expect(render(<FunctionalAreaCard />).container.innerHTML).toBe("");
  });
});
