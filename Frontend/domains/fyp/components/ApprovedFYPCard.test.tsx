/**
 * Tests for ApprovedFYPCard — the end of Release 0.5.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { makeFYP } from "../testFYP";
import { ApprovedFYPCard } from "./ApprovedFYPCard";

const mocks = vi.hoisted(() => ({ state: null as GreyUIState | null }));

vi.mock("@/core/grey-agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/core/grey-agent")>();
  return { ...actual, useGreyAgent: () => ({ state: mocks.state, isLoading: false, error: null }) };
});

function approvedState(overrides: Partial<GreyUIState> = {}): GreyUIState {
  const fyp = makeFYP();
  fyp.design = { ...fyp.design!, status: "approved" };
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "fyp_design",
    currentStage: "APPROVED_FYP",
    status: "complete",
    allowedActions: [],
    brainSummary: {
      industry: "Defense",
      branch: "Navy",
      functionalArea: "Maritime Surveillance",
      specificArea: "Vessel Behavior Monitoring",
      fypTitle: "Explainable alerts for unusual vessel movements",
    },
    eventData: { fyp },
    lastEventType: "fyp_direction_approved",
    ...overrides,
  };
}

afterEach(cleanup);

describe("ApprovedFYPCard", () => {
  it("summarises the approved FYP and where it sits", () => {
    mocks.state = approvedState();
    render(<ApprovedFYPCard />);

    expect(screen.getByRole("heading", { name: "Explainable alerts for unusual vessel movements" })).toBeTruthy();
    expect(screen.getByText("Defense → Navy → Maritime Surveillance → Vessel Behavior Monitoring")).toBeTruthy();
    expect(screen.getByText("Coastal monitoring analysts")).toBeTruthy();
    expect(screen.getByText(/backed by 2 sources saved in your Project Brain/)).toBeTruthy();
    expect(screen.queryAllByRole("button")).toHaveLength(0);           // nothing left to decide here
  });

  it("falls back to the Brain summary for the title", () => {
    mocks.state = approvedState({ eventData: {} });
    render(<ApprovedFYPCard />);
    expect(screen.getByRole("heading", { name: "Explainable alerts for unusual vessel movements" })).toBeTruthy();
  });

  it("shows nothing before approval", () => {
    mocks.state = approvedState({ currentStage: "FYP_DESIGN" });
    expect(render(<ApprovedFYPCard />).container.innerHTML).toBe("");
  });
});
