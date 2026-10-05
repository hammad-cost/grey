/**
 * Tests for ProblemOptions — the student's mandatory problem choice.
 *
 * The Grey adapter is replaced with a fake, so each test sets the exact UI
 * state it needs and checks which action was called. No backend is needed.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { makeProblem } from "../testProblems";
import { ProblemOptions } from "./ProblemOptions";

const mocks = vi.hoisted(() => ({
  selectProblem: vi.fn(),
  state: null as GreyUIState | null,
  isLoading: false,
}));

vi.mock("@/core/grey-agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/core/grey-agent")>();
  return {
    ...actual,
    useGreyAgent: () => ({ state: mocks.state, isLoading: mocks.isLoading, error: null }),
    useGreyActions: () => ({ selectProblem: mocks.selectProblem }),
  };
});

/** The UI state right after the backend's "problem_options_ready" event. */
function optionsState(overrides: Partial<GreyUIState> = {}, provider = "fake"): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "discovery",
    currentStage: "PROBLEM_OPTIONS",
    status: "awaiting_user",
    allowedActions: ["selectProblem"],
    brainSummary: { industry: "Defense", branch: "Navy" },
    eventData: {
      problems: [makeProblem(1), makeProblem(2), makeProblem(3)],
      summary: { options: 3, provider },
    },
    lastEventType: "problem_options_ready",
    ...overrides,
  };
}

beforeEach(() => {
  mocks.selectProblem.mockReset();
  mocks.selectProblem.mockResolvedValue(undefined);
  mocks.state = optionsState();
  mocks.isLoading = false;
});

afterEach(cleanup);

describe("ProblemOptions", () => {
  it("shows nothing outside the PROBLEM_OPTIONS stage", () => {
    mocks.state = optionsState({ currentStage: "EVIDENCE_RESEARCH" });
    const { container } = render(<ProblemOptions />);
    expect(container.innerHTML).toBe("");
  });

  it("shows nothing when the backend doesn't allow selectProblem", () => {
    mocks.state = optionsState({ allowedActions: [] });
    const { container } = render(<ProblemOptions />);
    expect(container.innerHTML).toBe("");
  });

  it("shows one card per problem, with the branch in the heading", () => {
    render(<ProblemOptions />);

    expect(screen.getByRole("heading", { name: "Grey found 3 real problems in Navy" })).toBeTruthy();
    expect(screen.getAllByRole("article")).toHaveLength(3);
  });

  it("skips malformed problems instead of crashing", () => {
    mocks.state = optionsState({
      eventData: { problems: [makeProblem(1), { id: "broken" }, makeProblem(2)], summary: {} },
    });
    render(<ProblemOptions />);
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("labels sample data", () => {
    render(<ProblemOptions />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("does not label real data as sample", () => {
    const real = (n: number) =>
      makeProblem(n, {
        evidence: makeProblem(n).evidence.map((s) => ({ ...s, url: `https://real-site-${n}.org/page` })),
      });
    mocks.state = optionsState({ eventData: { problems: [real(1), real(2), real(3)], summary: { provider: "groq" } } });
    render(<ProblemOptions />);
    expect(screen.queryByText("Sample data")).toBeNull();
  });

  it("asks for confirmation before choosing", () => {
    render(<ProblemOptions />);

    fireEvent.click(screen.getAllByRole("button", { name: "Choose this problem" })[1]);

    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText("Build your FYP around “Problem 2: abnormal vessel movement detection”?")).toBeTruthy();
    expect(mocks.selectProblem).not.toHaveBeenCalled();
  });

  it("confirming calls selectProblem with that problem's id", () => {
    render(<ProblemOptions />);
    fireEvent.click(screen.getAllByRole("button", { name: "Choose this problem" })[1]);

    fireEvent.click(screen.getByRole("button", { name: "Yes, build my FYP around this" }));

    expect(mocks.selectProblem).toHaveBeenCalledWith("p-2");
  });

  it("cancelling closes the confirmation without choosing", () => {
    render(<ProblemOptions />);
    fireEvent.click(screen.getAllByRole("button", { name: "Choose this problem" })[0]);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocks.selectProblem).not.toHaveBeenCalled();
  });

  it("disables choosing while Grey is saving", () => {
    mocks.isLoading = true;
    render(<ProblemOptions />);
    const buttons = screen.getAllByRole("button", { name: "Choose this problem" }) as HTMLButtonElement[];
    expect(buttons.every((b) => b.disabled)).toBe(true);
  });
});
