/**
 * Tests for ProposalWorkspace, CompletedProposalCard and proposal.ts (Release 0.14).
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import type { ProposalView } from "../proposal";
import { readProposal } from "../proposal";
import { CompletedProposalCard } from "./CompletedProposalCard";
import { ProposalWorkspace } from "./ProposalWorkspace";

const mocks = vi.hoisted(() => ({
  generateProposal: vi.fn(),
  rewriteProposalSection: vi.fn(),
  finalizeProposal: vi.fn(),
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
      generateProposal: mocks.generateProposal,
      rewriteProposalSection: mocks.rewriteProposalSection,
      finalizeProposal: mocks.finalizeProposal,
    }),
  };
});

function makeView(overrides: Partial<ProposalView> = {}): ProposalView {
  return {
    fyp_title: "Explainable alerts",
    rewrites_left: 3,
    max_rewrites: 3,
    rewritable_sections: ["introduction", "objectives"],
    proposal: {
      id: "p-1",
      status: "draft",
      rewrites_used: 0,
      proposal: {
        title: "Explainable alerts",
        sections: [
          { id: "project_title", title: "Project Title", paragraphs: ["Explainable alerts"], items: [], sources: ["Approved FYP design"], written_by: "grey" },
          { id: "introduction", title: "Introduction", paragraphs: ["Operators review tracks by hand [1]."], items: [], sources: ["Chosen problem"], written_by: "model" },
          { id: "objectives", title: "Objectives", paragraphs: [], items: ["Build the checker.", "Evaluate it."], sources: ["Approved scope"], written_by: "model" },
          { id: "dataset", title: "Dataset", paragraphs: ["AIS tracks — public dataset."], items: ["Size: 12,000 tracks"], sources: ["Selected dataset"], written_by: "grey" },
          { id: "references", title: "References", paragraphs: [], items: ["[1] Harbor report"], sources: ["Verified evidence sources"], written_by: "grey" },
        ],
        references: [{ number: 1, title: "Harbor report", organization: "Harbor Systems", url: "https://harbor.example/r",
                       published: "2026-01-01", source_type: "government_report" }],
      },
    },
    ...overrides,
  };
}

function reviewState(overrides: Partial<GreyUIState> = {}, view = makeView()): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "proposal",
    currentStage: "PROPOSAL_GENERATION",
    status: "awaiting_user",
    allowedActions: ["finalizeProposal", "rewriteProposalSection"],
    brainSummary: {},
    eventData: { proposal: view },
    lastEventType: "proposal_ready",
    ...overrides,
  };
}

beforeEach(() => {
  for (const action of [mocks.generateProposal, mocks.rewriteProposalSection, mocks.finalizeProposal]) {
    action.mockReset();
    action.mockResolvedValue({});
  }
  mocks.isLoading = false;
  mocks.error = null;
});

afterEach(cleanup);

describe("readProposal", () => {
  it("reads the view and drops references without a real link", () => {
    const view = makeView();
    view.proposal!.proposal.references.push({ number: 2, title: "Bad", organization: "", url: "javascript:x", published: null, source_type: "" });
    expect(readProposal({ proposal: view })?.proposal?.proposal.references).toHaveLength(1);
    expect(readProposal({})).toBeNull();
  });
});

describe("ProposalWorkspace", () => {
  it("shows nothing before the proposal", () => {
    mocks.state = reviewState({ currentStage: "SUPERVISOR_READY", lastEventType: "supervisor_ready_confirmed" });
    expect(render(<ProposalWorkspace />).container.innerHTML).toBe("");
  });

  it("shows the checklist while Grey writes, and Try again after a failure", () => {
    mocks.state = reviewState({ status: "running", allowedActions: [], lastEventType: "proposal_progress",
      eventData: { steps: [{ id: "building_sections", label: "Building sections", state: "active" }] } });
    render(<ProposalWorkspace />);
    expect(screen.getByText("Grey is writing your proposal…")).toBeTruthy();
    cleanup();
    mocks.state = reviewState({ status: "blocked", allowedActions: ["generateProposal"], lastEventType: "proposal_failed",
      eventData: { message: "Grey couldn't finish your proposal right now." } });
    render(<ProposalWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.generateProposal).toHaveBeenCalledOnce();
  });

  it("shows every section with its sources, numbered objectives and linked references", () => {
    mocks.state = reviewState();
    render(<ProposalWorkspace />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Explainable alerts");
    const contents = within(screen.getByRole("navigation", { name: "Contents" })).getAllByRole("link");
    expect(contents.map((l) => l.textContent)).toEqual(["Introduction", "Objectives", "Dataset", "References"]);
    const intro = screen.getByRole("article", { name: "Introduction" });
    expect(within(intro).getByText("Written by Grey from: Chosen problem")).toBeTruthy();
    expect(within(screen.getByRole("article", { name: "Dataset" })).getByText("Built from: Selected dataset")).toBeTruthy();
    expect(within(screen.getByRole("article", { name: "Objectives" })).getByRole("list").tagName).toBe("OL");
    const reference = within(screen.getByRole("list", { name: "References" })).getByRole("link");
    expect(reference.getAttribute("href")).toBe("https://harbor.example/r");
    expect(screen.getByRole("link", { name: "Download as Markdown" }).getAttribute("href"))
      .toMatch(/\/projects\/w_123\/proposal\/markdown$/);
  });

  it("offers rewrites only on the narrative sections", () => {
    mocks.state = reviewState();
    render(<ProposalWorkspace />);
    expect(screen.getByText("3 of 3 section rewrites left.")).toBeTruthy();
    expect(within(screen.getByRole("article", { name: "Dataset" })).queryByRole("button")).toBeNull();
    fireEvent.click(within(screen.getByRole("article", { name: "Introduction" })).getByRole("button", { name: "Rewrite this section" }));
    expect(mocks.rewriteProposalSection).toHaveBeenCalledWith("introduction");
  });

  it("keeps the proposal after a failed rewrite and confirms before finalizing", () => {
    mocks.state = reviewState({ lastEventType: "proposal_failed",
      eventData: { proposal: makeView(), message: "Grey couldn't rewrite that section right now." } });
    render(<ProposalWorkspace />);
    expect(screen.getByRole("status").textContent).toContain("couldn't rewrite");
    fireEvent.click(screen.getByRole("button", { name: "Finalize proposal" }));
    expect(mocks.finalizeProposal).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Yes, finalize it" }));
    expect(mocks.finalizeProposal).toHaveBeenCalledWith("p-1");
  });
});

describe("CompletedProposalCard", () => {
  it("celebrates the end of the journey with a download", () => {
    mocks.state = reviewState({ currentStage: "COMPLETE", lastEventType: "proposal_finalized" });
    render(<CompletedProposalCard />);
    expect(screen.getByText("Your FYP journey is complete")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download your proposal" }).getAttribute("href"))
      .toMatch(/\/proposal\/markdown$/);
  });
});
