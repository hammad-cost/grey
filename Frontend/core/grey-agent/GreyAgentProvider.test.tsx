/**
 * Tests for the Grey UI Adapter (GreyAgentProvider + hooks).
 *
 * Uses the real provider; only the network (fetch) is faked.
 * Checks that backend events are turned into the GreyUIState the UI relies on.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyEvent, GreyUIState } from "./types";
import { GreyAgentProvider, useGreyActions, useGreyAgent, useGreyUIState } from "./index";
import { fakeBody } from "./testUtils";

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
  status: "awaiting_user",
  data: { industry: "Finance", branch: "Fraud Detection" },
  brain_patch: {
    branch: "Fraud Detection",
    branch_status: "approved",
    workflow_state: "EVIDENCE_RESEARCH",
  },
  allowed_actions: ["startResearch"],
};

/** A research event, shaped like the backend's streamed events. */
function researchEvent(
  type: string,
  completed: number,
  extra: Partial<GreyEvent> = {}
): GreyEvent {
  return {
    type,
    workspace_id: "w_123",
    domain: "fyp",
    workflow: "discovery",
    stage: "EVIDENCE_RESEARCH",
    status: "running",
    data: { label: `${type} label`, completed_steps: completed, total_steps: 6 },
    brain_patch: {},
    allowed_actions: [],
    ...extra,
  };
}

const researchStarted = researchEvent("research_started", 0, {
  brain_patch: { research_status: "running" },
});
const sourcesFound = researchEvent("sources_found", 1);
const researchCompleted = researchEvent("research_completed", 6, {
  status: "complete",
  brain_patch: {
    research_status: "complete",
    evidence_count: 13,
    high_quality_evidence_count: 7,
  },
});

/** research_completed as Release 0.3 sends it: problems should be found next. */
const researchCompletedFindProblems: GreyEvent = {
  ...researchCompleted,
  allowed_actions: ["extractProblems"],
};

const problemsStarted: GreyEvent = {
  ...researchEvent("problem_extraction_started", 0),
  brain_patch: { problem_status: "running" },
};

const problemOptionsReady: GreyEvent = {
  type: "problem_options_ready",
  workspace_id: "w_123",
  domain: "fyp",
  workflow: "discovery",
  stage: "PROBLEM_OPTIONS",
  status: "awaiting_user",
  data: {
    label: "Problem options ready",
    completed_steps: 4,
    total_steps: 4,
    problems: [{ id: "p-1", title: "Problem one" }, { id: "p-2", title: "Problem two" }, { id: "p-3", title: "Problem three" }],
  },
  brain_patch: { workflow_state: "PROBLEM_OPTIONS", problem_status: "options_ready", problem_option_count: 3 },
  allowed_actions: ["selectProblem"],
};

const problemSelected: GreyEvent = {
  type: "problem_selected",
  workspace_id: "w_123",
  domain: "fyp",
  workflow: "discovery",
  stage: "PROBLEM_SELECTED",
  status: "complete",
  data: { problem: { id: "p-2", title: "Problem two" } },
  brain_patch: {
    workflow_state: "PROBLEM_SELECTED",
    selected_problem_id: "p-2",
    selected_problem_title: "Problem two",
  },
  allowed_actions: [],
};

/** problem_selected as Release 0.5 sends it: the FYP should be designed next. */
const problemSelectedDesignNext: GreyEvent = { ...problemSelected, allowed_actions: ["designFYP"] };

/** An FYP design event, shaped like the backend's streamed events (Release 0.5). */
function fypEvent(type: string, extra: Partial<GreyEvent> = {}): GreyEvent {
  return {
    type,
    workspace_id: "w_123",
    domain: "fyp",
    workflow: "fyp_design",
    stage: "PROBLEM_SELECTED",
    status: "running",
    data: { label: `${type} label`, completed_steps: 1, total_steps: 4 },
    brain_patch: {},
    allowed_actions: [],
    ...extra,
  };
}

const fypStarted = fypEvent("fyp_design_started", { brain_patch: { fyp_design_status: "running" } });
const areaClassified = fypEvent("area_classified", {
  stage: "AREA_CLASSIFICATION",
  brain_patch: {
    workflow_state: "AREA_CLASSIFICATION",
    functional_area: "Maritime Surveillance",
    specific_area: "Vessel Behavior Monitoring",
  },
});
const fypReady = fypEvent("fyp_direction_ready", {
  stage: "FYP_DESIGN",
  status: "awaiting_user",
  data: { label: "Your FYP design is ready", completed_steps: 4, total_steps: 4, fyp: { design: { id: "d-1" } } },
  brain_patch: {
    workflow_state: "FYP_DESIGN",
    fyp_design_id: "d-1",
    fyp_title: "Vessel alerts",
    fyp_design_status: "draft",
    fyp_adjustments_left: 3,
  },
  allowed_actions: ["approveFYPDirection", "adjustFYPDirection"],
});
const fypApproved = fypEvent("fyp_direction_approved", {
  stage: "APPROVED_FYP",
  status: "complete",
  brain_patch: { workflow_state: "APPROVED_FYP", fyp_design_status: "approved" },
});

/** A streamed reply with these events, one JSON per line. */
function streamOf(...events: GreyEvent[]) {
  return { ok: true, body: fakeBody(events.map((e) => JSON.stringify(e) + "\n")) };
}

/** A tiny test component that exposes adapter state and actions. */
function Probe() {
  const state = useGreyUIState();
  const { error } = useGreyAgent();
  const {
    startProject, selectIndustry, selectBranch, startResearch, extractProblems, selectProblem,
    designFYP, adjustFYPDirection, approveFYPDirection,
  } = useGreyActions();
  return (
    <>
      <button onClick={() => startProject()}>start</button>
      <button onClick={() => selectIndustry("Finance")}>pick finance</button>
      <button onClick={() => selectBranch("Fraud Detection")}>pick fraud detection</button>
      <button onClick={() => startResearch().catch(() => {})}>research</button>
      <button onClick={() => extractProblems().catch(() => {})}>find problems</button>
      <button onClick={() => selectProblem("p-2").catch(() => {})}>pick problem 2</button>
      <button onClick={() => designFYP().catch(() => {})}>design fyp</button>
      <button onClick={() => adjustFYPDirection("make_simpler", "  For port staff ").catch(() => {})}>adjust</button>
      <button onClick={() => adjustFYPDirection("reduce_complexity", "   ").catch(() => {})}>adjust no note</button>
      <button onClick={() => approveFYPDirection("d-1").catch(() => {})}>approve</button>
      <pre data-testid="state">{JSON.stringify(state)}</pre>
      <p data-testid="error">{error ?? ""}</p>
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

    // Both decisions are in brainSummary, and research can start next.
    const state = readState();
    expect(state.status).toBe("awaiting_user");
    expect(state.allowedActions).toEqual(["startResearch"]);
    expect(state.brainSummary).toEqual({
      workflowState: "EVIDENCE_RESEARCH",
      industry: "Finance",
      industryStatus: "approved",
      branch: "Fraud Detection",
      branchStatus: "approved",
    });
  });

  it("startResearch applies each streamed event and ends with the research summary", async () => {
    replyWith(projectCreated);
    const lines = [researchStarted, sourcesFound, researchCompleted]
      .map((e) => JSON.stringify(e) + "\n");
    fetchMock.mockResolvedValueOnce({ ok: true, body: fakeBody(lines) });
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));

    fireEvent.click(screen.getByText("research"));
    await waitFor(() => expect(readState().status).toBe("complete"));

    const [url, options] = fetchMock.mock.calls[1];
    expect(url).toMatch(/\/projects\/w_123\/research$/);
    expect(options.method).toBe("POST");

    const state = readState();
    expect(state.progress).toEqual({ label: "research_completed label", completed: 6, total: 6 });
    expect(state.brainSummary).toMatchObject({
      researchStatus: "complete",
      evidenceCount: 13,
      highQualityEvidenceCount: 7,
    });
  });

  it("startResearch shows an error if the stream stops before research ends", async () => {
    replyWith(projectCreated);
    fetchMock.mockResolvedValueOnce({
      ok: true,
      body: fakeBody([JSON.stringify(researchStarted) + "\n"]),
    });
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("research"));

    await waitFor(() =>
      expect(screen.getByTestId("error").textContent).toMatch(/connection to Grey was lost/)
    );
  });

  it("startResearch shows the backend's message when research can't start", async () => {
    replyWith(projectCreated);
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({ detail: "Research is already running for 'w_123'." }),
    });
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("research"));

    await waitFor(() =>
      expect(screen.getByTestId("error").textContent).toBe("Research is already running for 'w_123'.")
    );
  });
  it("startResearch finds problems straight away when research allows it", async () => {
    replyWith(projectCreated);
    fetchMock.mockResolvedValueOnce(streamOf(researchStarted, researchCompletedFindProblems));
    fetchMock.mockResolvedValueOnce(streamOf(problemsStarted, problemOptionsReady));
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("research"));
    await waitFor(() => expect(readState().currentStage).toBe("PROBLEM_OPTIONS"));

    const urls = fetchMock.mock.calls.map(([url]) => url);
    expect(urls[1]).toMatch(/\/projects\/w_123\/research$/);
    expect(urls[2]).toMatch(/\/projects\/w_123\/problems$/);
    expect(fetchMock.mock.calls[2][1].method).toBe("POST");

    const state = readState();
    expect(state.allowedActions).toEqual(["selectProblem"]);
    expect(state.eventData?.problems).toHaveLength(3);
    expect(state.brainSummary).toMatchObject({
      researchStatus: "complete",
      problemStatus: "options_ready",
      problemOptionCount: 3,
      workflowState: "PROBLEM_OPTIONS",
    });
  });

  it("startResearch does not look for problems when research failed", async () => {
    replyWith(projectCreated);
    const failed = researchEvent("research_failed", 0, {
      status: "blocked",
      allowed_actions: ["startResearch"],
    });
    fetchMock.mockResolvedValueOnce(streamOf(researchStarted, failed));
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("research"));
    await waitFor(() => expect(readState().status).toBe("blocked"));

    expect(fetchMock).toHaveBeenCalledTimes(2);   // create project + research only
  });

  it("extractProblems retries finding problems on its own", async () => {
    replyWith(projectCreated);
    fetchMock.mockResolvedValueOnce(streamOf(problemsStarted, problemOptionsReady));
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("find problems"));
    await waitFor(() => expect(readState().currentStage).toBe("PROBLEM_OPTIONS"));

    expect(fetchMock.mock.calls[1][0]).toMatch(/\/projects\/w_123\/problems$/);
  });

  it("extractProblems shows an error if the stream stops early", async () => {
    replyWith(projectCreated);
    fetchMock.mockResolvedValueOnce(streamOf(problemsStarted));
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("find problems"));

    await waitFor(() =>
      expect(screen.getByTestId("error").textContent).toMatch(/connection to Grey was lost during finding problems/)
    );
  });

  it("selectProblem posts the chosen problem and stores it in camelCase", async () => {
    replyWith(projectCreated);
    replyWith(problemSelected);
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("pick problem 2"));
    await waitFor(() => expect(readState().currentStage).toBe("PROBLEM_SELECTED"));

    const [url, options] = fetchMock.mock.calls[1];
    expect(url).toMatch(/\/projects\/w_123\/problem$/);
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ problem_id: "p-2" });
    expect(readState().brainSummary).toMatchObject({
      selectedProblemId: "p-2",
      selectedProblemTitle: "Problem two",
      workflowState: "PROBLEM_SELECTED",
    });
  });

  it("selectProblem shows the backend's message when the choice is rejected", async () => {
    replyWith(projectCreated);
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({ detail: "'p-2' is not one of this project's problem options." }),
    });
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("pick problem 2"));

    await waitFor(() =>
      expect(screen.getByTestId("error").textContent).toBe("'p-2' is not one of this project's problem options.")
    );
  });

  // ── Release 0.5: from problem to FYP ──────────────────────────────────────

  it("selectProblem designs the FYP straight away when the backend allows it", async () => {
    replyWith(projectCreated);
    replyWith(problemSelectedDesignNext);
    fetchMock.mockResolvedValueOnce(streamOf(fypStarted, areaClassified, fypReady));
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("pick problem 2"));
    await waitFor(() => expect(readState().currentStage).toBe("FYP_DESIGN"));

    expect(fetchMock.mock.calls[2][0]).toMatch(/\/projects\/w_123\/fyp-design$/);
    expect(fetchMock.mock.calls[2][1].method).toBe("POST");
    const state = readState();
    expect(state.allowedActions).toEqual(["approveFYPDirection", "adjustFYPDirection"]);
    expect(state.brainSummary).toMatchObject({
      selectedProblemTitle: "Problem two",
      functionalArea: "Maritime Surveillance",
      specificArea: "Vessel Behavior Monitoring",
      fypDesignId: "d-1",
      fypTitle: "Vessel alerts",
      fypDesignStatus: "draft",
      fypAdjustmentsLeft: 3,
      workflowState: "FYP_DESIGN",
    });
  });

  it("selectProblem stops after saving the choice when no design is allowed", async () => {
    replyWith(projectCreated);
    replyWith(problemSelected);
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("pick problem 2"));
    await waitFor(() => expect(readState().currentStage).toBe("PROBLEM_SELECTED"));

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("designFYP retries the design on its own", async () => {
    replyWith(projectCreated);
    fetchMock.mockResolvedValueOnce(streamOf(fypStarted, fypReady));
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("design fyp"));
    await waitFor(() => expect(readState().currentStage).toBe("FYP_DESIGN"));

    expect(fetchMock.mock.calls[1][0]).toMatch(/\/projects\/w_123\/fyp-design$/);
  });

  it("designFYP shows an error if the stream stops early", async () => {
    replyWith(projectCreated);
    fetchMock.mockResolvedValueOnce(streamOf(fypStarted));
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("design fyp"));

    await waitFor(() =>
      expect(screen.getByTestId("error").textContent).toMatch(/connection to Grey was lost during designing your fyp/)
    );
  });

  it("adjustFYPDirection posts the controlled adjustment and a trimmed note", async () => {
    replyWith(projectCreated);
    fetchMock.mockResolvedValueOnce(streamOf(fypStarted, fypReady));
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("adjust"));
    await waitFor(() => expect(readState().lastEventType).toBe("fyp_direction_ready"));

    const [url, options] = fetchMock.mock.calls[1];
    expect(url).toMatch(/\/projects\/w_123\/fyp-design\/adjust$/);
    expect(options.method).toBe("POST");
    expect(options.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(options.body)).toEqual({ adjustment: "make_simpler", note: "For port staff" });
  });

  it("adjustFYPDirection leaves out an empty note", async () => {
    replyWith(projectCreated);
    fetchMock.mockResolvedValueOnce(streamOf(fypStarted, fypReady));
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("adjust no note"));
    await waitFor(() => expect(readState().lastEventType).toBe("fyp_direction_ready"));

    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ adjustment: "reduce_complexity" });
  });

  it("approveFYPDirection posts the design id and finishes at APPROVED_FYP", async () => {
    replyWith(projectCreated);
    replyWith(fypApproved);
    render(<GreyAgentProvider><Probe /></GreyAgentProvider>);

    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(readState().workspaceId).toBe("w_123"));
    fireEvent.click(screen.getByText("approve"));
    await waitFor(() => expect(readState().currentStage).toBe("APPROVED_FYP"));

    const [url, options] = fetchMock.mock.calls[1];
    expect(url).toMatch(/\/projects\/w_123\/fyp-design\/approve$/);
    expect(JSON.parse(options.body)).toEqual({ design_id: "d-1" });
    expect(readState().brainSummary).toMatchObject({ fypDesignStatus: "approved", workflowState: "APPROVED_FYP" });
  });
});
