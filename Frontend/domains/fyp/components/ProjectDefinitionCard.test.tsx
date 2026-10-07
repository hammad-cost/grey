/**
 * Tests for ProjectDefinitionCard — defining the project, moving features
 * between scope lists, and approving the scope (Release 0.6).
 *
 * The Grey adapter is replaced with a fake, so each test sets the exact UI
 * state it needs and checks which action was called. No backend is needed.
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { makeDefinition } from "../testDefinition";
import { ProjectDefinitionCard } from "./ProjectDefinitionCard";

const mocks = vi.hoisted(() => ({
  defineProject: vi.fn(),
  moveScopeItem: vi.fn(),
  approveScope: vi.fn(),
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
      defineProject: mocks.defineProject,
      moveScopeItem: mocks.moveScopeItem,
      approveScope: mocks.approveScope,
    }),
  };
});

/** The UI state right after the backend's "project_definition_ready" event. */
function reviewState(overrides: Partial<GreyUIState> = {}, definition = makeDefinition()): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "project_definition",
    currentStage: "SCOPE",
    status: "awaiting_user",
    allowedActions: ["approveScope", "modifyScope"],
    brainSummary: { industry: "Defense", branch: "Navy" },
    eventData: { definition },
    lastEventType: "project_definition_ready",
    ...overrides,
  };
}

function runningState(): GreyUIState {
  return reviewState({
    currentStage: "APPROVED_FYP",
    status: "running",
    allowedActions: [],
    lastEventType: "project_definition_progress",
    eventData: {
      label: "Checking the definition against your FYP",
      steps: [
        { id: "defining_project", label: "Writing your problem definition, scope and solution", state: "done" },
        { id: "checking_definition", label: "Checking the definition against your FYP", state: "active" },
        { id: "saving_definition", label: "Saving it to your Project Brain", state: "pending" },
      ],
    },
  });
}

beforeEach(() => {
  for (const action of [mocks.defineProject, mocks.moveScopeItem, mocks.approveScope]) {
    action.mockReset();
    action.mockResolvedValue(undefined);
  }
  mocks.isLoading = false;
  mocks.error = null;
});

afterEach(cleanup);

describe("ProjectDefinitionCard", () => {
  it("shows nothing for other events or after approval", () => {
    mocks.state = reviewState({ lastEventType: "fyp_direction_approved" });
    expect(render(<ProjectDefinitionCard />).container.innerHTML).toBe("");
    cleanup();
    mocks.state = reviewState({ currentStage: "SCOPE_APPROVED", lastEventType: "scope_approved" });
    expect(render(<ProjectDefinitionCard />).container.innerHTML).toBe("");
  });

  it("shows Grey's live checklist while it works", () => {
    mocks.state = runningState();
    render(<ProjectDefinitionCard />);

    expect(screen.getByText("Grey is defining your project…")).toBeTruthy();
    const steps = screen.getByRole("list", { name: "Project definition steps" });
    expect(within(steps).getByText("Checking the definition against your FYP").closest("li")?.dataset.state)
      .toBe("active");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("offers Try again if the connection was lost while working", () => {
    mocks.state = runningState();
    mocks.error = "The connection to Grey was lost during defining your project. Please try again.";
    render(<ProjectDefinitionCard />);

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.defineProject).toHaveBeenCalledOnce();
  });

  it("shows the calm failure message and Try again", () => {
    mocks.state = reviewState({
      currentStage: "APPROVED_FYP",
      status: "blocked",
      allowedActions: ["defineProject"],
      lastEventType: "project_definition_failed",
      eventData: { message: "Grey couldn't finish defining your project right now." },
    });
    render(<ProjectDefinitionCard />);

    expect(screen.getByText("Your project could not be defined")).toBeTruthy();
    expect(screen.getByText("Grey couldn't finish defining your project right now.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.defineProject).toHaveBeenCalledOnce();
  });

  it("shows the problem definition, proposed solution and the three scope lists", () => {
    mocks.state = reviewState();
    render(<ProjectDefinitionCard />);

    expect(screen.getByRole("heading", { name: "Explainable alerts for unusual vessel movements" })).toBeTruthy();
    expect(screen.getByText("No simple tool explains each alert.")).toBeTruthy();                 // the gap
    // Who experiences the problem + who uses the system (from the approved design)
    expect(screen.getAllByText("Coastal monitoring analysts", { selector: "dd" })).toHaveLength(2);
    expect(screen.getByText("Vessel position reports over time")).toBeTruthy();
    expect(within(screen.getByRole("list", { name: "Main modules" })).getAllByRole("listitem")).toHaveLength(2);
    expect(within(screen.getByRole("list", { name: "How it works" })).getAllByRole("listitem")).toHaveLength(3);

    const core = screen.getByRole("list", { name: "Core scope" });
    expect(within(core).getAllByRole("listitem").map((li) => li.querySelector("p")?.textContent))
      .toEqual(["Report upload", "Track checking", "Alert list"]);
    expect(within(screen.getByRole("list", { name: "Optional scope" })).getAllByRole("listitem")).toHaveLength(1);
    expect(within(screen.getByRole("list", { name: "Out of scope" })).getAllByRole("listitem")).toHaveLength(2);
  });

  it("moves a feature to another list", () => {
    mocks.state = reviewState();
    render(<ProjectDefinitionCard />);

    fireEvent.click(screen.getByRole("button", { name: "Move Report export to Core" }));
    expect(mocks.moveScopeItem).toHaveBeenCalledWith("s-4", "core");
  });

  it("disables moves that would leave too few core features", () => {
    const definition = makeDefinition({ min_core_features: 3 });
    mocks.state = reviewState({}, definition);
    render(<ProjectDefinitionCard />);

    const button = screen.getByRole("button", { name: "Move Report upload to Optional" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("confirms the last move", () => {
    mocks.state = reviewState({ lastEventType: "scope_updated", eventData: { definition: makeDefinition(), moved: "Report export" } });
    render(<ProjectDefinitionCard />);
    expect(screen.getByRole("status").textContent).toBe("Moved “Report export”.");
  });

  it("asks to confirm before approving the scope", () => {
    mocks.state = reviewState();
    render(<ProjectDefinitionCard />);

    fireEvent.click(screen.getByRole("button", { name: "Approve scope" }));
    expect(mocks.approveScope).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Move / })).toBeNull();          // no moves while confirming

    fireEvent.click(screen.getByRole("button", { name: "Yes, approve my scope" }));
    expect(mocks.approveScope).toHaveBeenCalledWith("def-1");
  });

  it("can cancel the approval", () => {
    mocks.state = reviewState();
    render(<ProjectDefinitionCard />);

    fireEvent.click(screen.getByRole("button", { name: "Approve scope" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Approve scope" })).toBeTruthy();
    expect(mocks.approveScope).not.toHaveBeenCalled();
  });

  it("hides the controls the backend doesn't allow", () => {
    mocks.state = reviewState({ allowedActions: [] });
    render(<ProjectDefinitionCard />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
