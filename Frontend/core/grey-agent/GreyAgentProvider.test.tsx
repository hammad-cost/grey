/**
 * Tests for the Grey UI Adapter (GreyAgentProvider + hooks).
 *
 * Uses the real provider; only the network (fetch) is faked.
 * Checks that backend events are turned into the GreyUIState the UI relies on.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyEvent, GreyUIState } from "./types";
import { GreyAgentProvider, useGreyActions, useGreyUIState } from "./index";

// Backend events, shaped exactly like the FastAPI responses.
const projectCreated: GreyEvent = {
  type: "project_created",
  workspace_id: "w_123",
  domain: "fyp",
  workflow: "discovery",
  stage: "INDUSTRY_SELECTION",
  status: "awaiting_user",
  data: { available_industries: ["Healthcare", "Finance"] },
  brain_patch: { workflow_state: "INDUSTRY_SELECTION" },
  allowed_actions: ["selectIndustry", "askGrey"],
};

const industrySaved: GreyEvent = {
  type: "industry_saved",
  workspace_id: "w_123",
  domain: "fyp",
  workflow: "discovery",
  stage: "BRANCH_SELECTION",
  status: "awaiting_user",
  data: { industry: "Finance", available_branches: ["Banking", "Fraud Detection"] },
  brain_patch: { industry: "Finance", industry_status: "approved" },
  allowed_actions: ["selectBranch", "askGrey"],
};

const branchSaved: GreyEvent = {
  type: "branch_saved",
  workspace_id: "w_123",
  domain: "fyp",
  workflow: "discovery",
  stage: "EVIDENCE_RESEARCH",
  status: "complete",
  data: { industry: "Finance", branch: "Fraud Detection" },
  brain_patch: {
    branch: "Fraud Detection",
    branch_status: "approved",
    workflow_state: "EVIDENCE_RESEARCH",
  },
  allowed_actions: [],
};

/** A tiny test component that exposes adapter state and actions. */
function Probe() {
  const state = useGreyUIState();
  const { startProject, selectIndustry, selectBranch } = useGreyActions();
  return (
    <>
      <button onClick={() => startProject()}>start</button>
      <button onClick={() => selectIndustry("Finance")}>pick finance</button>
      <button onClick={() => selectBranch("Fraud Detection")}>pick fraud detection</button>
      <pre data-testid="state">{JSON.stringify(state)}</pre>
    </>
  );
}

function readState(): GreyUIState {
  return JSON.parse(screen.getByTestId("state").textContent ?? "{}");
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function replyWith(event: GreyEvent) {
  fetchMock.mockResolvedValueOnce({ ok: true, json: async () => event });
}

describe("GreyAgentProvider", () => {
  it("keeps the latest event data so components can read the industry list", async () => {
    replyWith(projectCreated);
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));

    await waitFor(() => expect(readState().currentStage).toBe("INDUSTRY_SELECTION"));
    const state = readState();
    expect(state.workspaceId).toBe("w_123");
    expect(state.allowedActions).toContain("selectIndustry");
    expect(state.eventData?.available_industries).toEqual(["Healthcare", "Finance"]);
  });

  it("selectIndustry posts the chosen industry and stores it in camelCase", async () => {
    replyWith(projectCreated);
    replyWith(industrySaved);
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));

    fireEvent.click(screen.getByText("pick finance"));
    await waitFor(() => expect(readState().currentStage).toBe("BRANCH_SELECTION"));

    // The request went to the right endpoint with the right body.
    const [url, options] = fetchMock.mock.calls[1];
    expect(url).toMatch(/\/projects\/w_123\/industry$/);
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ industry: "Finance" });

    // brain_patch (snake_case) was merged into brainSummary (camelCase).
    expect(readState().brainSummary).toEqual({
      workflowState: "INDUSTRY_SELECTION",
      industry: "Finance",
      industryStatus: "approved",
    });
  });

  it("selectBranch posts the chosen branch and finishes at EVIDENCE_RESEARCH", async () => {
    replyWith(projectCreated);
    replyWith(industrySaved);
    replyWith(branchSaved);
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().currentStage).toBe("INDUSTRY_SELECTION"));
    fireEvent.click(screen.getByText("pick finance"));
    await waitFor(() => expect(readState().currentStage).toBe("BRANCH_SELECTION"));

    // The branch list for the chosen industry is available to BranchSelector.
    expect(readState().eventData?.available_branches).toEqual(["Banking", "Fraud Detection"]);

    fireEvent.click(screen.getByText("pick fraud detection"));
    await waitFor(() => expect(readState().currentStage).toBe("EVIDENCE_RESEARCH"));

    // The request went to the right endpoint with the right body.
    const [url, options] = fetchMock.mock.calls[2];
    expect(url).toMatch(/\/projects\/w_123\/branch$/);
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ branch: "Fraud Detection" });

    // Both decisions are in brainSummary, and no further actions are allowed.
    const state = readState();
    expect(state.status).toBe("complete");
    expect(state.allowedActions).toEqual([]);
    expect(state.brainSummary).toEqual({
      workflowState: "EVIDENCE_RESEARCH",
      industry: "Finance",
      industryStatus: "approved",
      branch: "Fraud Detection",
      branchStatus: "approved",
    });
  });
});
