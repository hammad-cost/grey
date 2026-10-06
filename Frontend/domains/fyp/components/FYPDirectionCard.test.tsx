/**
 * Tests for FYPDirectionCard — designing, reviewing, approving and adjusting
 * the FYP (Release 0.5).
 *
 * The Grey adapter is replaced with a fake, so each test sets the exact UI
 * state it needs and checks which action was called. No backend is needed.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { makeFYP } from "../testFYP";
import { FYPDirectionCard } from "./FYPDirectionCard";

const mocks = vi.hoisted(() => ({
  designFYP: vi.fn(),
  approveFYPDirection: vi.fn(),
  adjustFYPDirection: vi.fn(),
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
      designFYP: mocks.designFYP,
      approveFYPDirection: mocks.approveFYPDirection,
      adjustFYPDirection: mocks.adjustFYPDirection,
    }),
  };
});

/** The UI state right after the backend's "fyp_direction_ready" event. */
function reviewState(overrides: Partial<GreyUIState> = {}, fyp = makeFYP()): GreyUIState {
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "fyp_design",
    currentStage: "FYP_DESIGN",
    status: "awaiting_user",
    allowedActions: ["approveFYPDirection", "adjustFYPDirection"],
    brainSummary: { industry: "Defense", branch: "Navy" },
    eventData: { kind: "initial", fyp },
    lastEventType: "fyp_direction_ready",
    ...overrides,
  };
}

function runningState(kind = "initial"): GreyUIState {
  return reviewState({
    currentStage: "AREA_CLASSIFICATION",
    status: "running",
    allowedActions: [],
    lastEventType: "fyp_design_progress",
    eventData: {
      kind,
      label: "Designing a student-sized FYP",
      steps: [
        { id: "classifying_area", label: "Finding where your project fits", state: "done" },
        { id: "designing_fyp", label: "Designing a student-sized FYP", state: "active" },
        { id: "checking_design", label: "Checking the design against your problem", state: "pending" },
      ],
    },
  });
}

beforeEach(() => {
  for (const action of [mocks.designFYP, mocks.approveFYPDirection, mocks.adjustFYPDirection]) {
    action.mockReset();
    action.mockResolvedValue(undefined);
  }
  mocks.state = reviewState();
  mocks.isLoading = false;
  mocks.error = null;
});

afterEach(cleanup);

describe("FYPDirectionCard — when it shows", () => {
  it("shows nothing before the FYP design starts", () => {
    mocks.state = reviewState({ currentStage: "PROBLEM_SELECTED", lastEventType: "problem_selected" });
    expect(render(<FYPDirectionCard />).container.innerHTML).toBe("");
  });

  it("shows nothing after approval", () => {
    mocks.state = reviewState({ currentStage: "APPROVED_FYP", lastEventType: "fyp_direction_approved" });
    expect(render(<FYPDirectionCard />).container.innerHTML).toBe("");
  });
});

describe("FYPDirectionCard — working and failed", () => {
  it("shows the backend's checklist while Grey designs the FYP", () => {
    mocks.state = runningState();
    render(<FYPDirectionCard />);
    expect(screen.getByText("Grey is turning your problem into an FYP…")).toBeTruthy();
    const items = screen.getAllByRole("listitem");
    expect(items.map((i) => i.getAttribute("data-state"))).toEqual(["done", "active", "pending"]);
  });

  it("says it is redesigning during an adjustment", () => {
    mocks.state = runningState("adjustment");
    render(<FYPDirectionCard />);
    expect(screen.getByText("Grey is redesigning your FYP…")).toBeTruthy();
  });

  it("shows the calm message and Try again after a failed first design", () => {
    mocks.state = reviewState({
      currentStage: "PROBLEM_SELECTED",
      status: "blocked",
      allowedActions: ["designFYP"],
      lastEventType: "fyp_design_failed",
      eventData: { kind: "initial", message: "Grey couldn't finish designing your FYP right now." },
    });
    render(<FYPDirectionCard />);

    expect(screen.getByText("Your FYP could not be designed")).toBeTruthy();
    expect(screen.getByText("Grey couldn't finish designing your FYP right now.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.designFYP).toHaveBeenCalledOnce();
  });

  it("offers Try again if the connection was lost during the first design", () => {
    mocks.state = runningState();
    mocks.error = "The connection to Grey was lost.";
    render(<FYPDirectionCard />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.designFYP).toHaveBeenCalledOnce();
  });
});

describe("FYPDirectionCard — review", () => {
  it("shows the proposed FYP", () => {
    render(<FYPDirectionCard />);
    for (const text of ["Explainable alerts for unusual vessel movements",
                        "A web tool that flags unusual vessel tracks and explains each alert.",
                        "Coastal monitoring analysts", "Vessel position reports over time",
                        "A ranked list of unusual tracks with reasons", "Alerts an analyst can check in seconds."]) {
      expect(screen.getByText(text)).toBeTruthy();
    }
    expect(screen.getByText("3 of 3 redesigns left")).toBeTruthy();
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("opens Why this FYP with the evidence and its links", () => {
    render(<FYPDirectionCard />);
    fireEvent.click(screen.getByRole("button", { name: "Why this FYP?" }));

    expect(screen.getByText("One student builds only the alerting part of a surveillance system.",
                            { selector: "span" })).toBeTruthy();
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0].getAttribute("href")).toBe("https://harbor-1.example/report");
    expect(links[0].getAttribute("target")).toBe("_blank");
    expect(screen.getByText("“Operators review vessel tracking data manually.”")).toBeTruthy();
  });

  it("asks to confirm before approving, then approves the current design", () => {
    render(<FYPDirectionCard />);
    fireEvent.click(screen.getByRole("button", { name: "Approve this FYP" }));
    expect(mocks.approveFYPDirection).not.toHaveBeenCalled();

    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Yes, approve my FYP" }));
    expect(mocks.approveFYPDirection).toHaveBeenCalledWith("d-1");
  });

  it("cancel closes the confirmation without approving", () => {
    render(<FYPDirectionCard />);
    fireEvent.click(screen.getByRole("button", { name: "Approve this FYP" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocks.approveFYPDirection).not.toHaveBeenCalled();
  });

  it("adjust offers only the four controlled options and an optional short note", () => {
    render(<FYPDirectionCard />);
    fireEvent.click(screen.getByRole("button", { name: "Adjust" }));

    const options = screen.getAllByRole("radio").map((r) => (r as HTMLInputElement).value);
    expect(options).toEqual(["make_simpler", "change_target_user", "change_system_focus", "reduce_complexity"]);
    const submit = screen.getByRole("button", { name: "Redesign my FYP" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);                       // an option must be chosen first
    expect((screen.getByLabelText("Optional note") as HTMLTextAreaElement).maxLength).toBe(200);
  });

  it("sends the chosen adjustment and note", () => {
    render(<FYPDirectionCard />);
    fireEvent.click(screen.getByRole("button", { name: "Adjust" }));
    fireEvent.click(screen.getByLabelText("Change target user"));
    fireEvent.change(screen.getByLabelText("Optional note"), { target: { value: "For port staff" } });
    fireEvent.click(screen.getByRole("button", { name: "Redesign my FYP" }));

    expect(mocks.adjustFYPDirection).toHaveBeenCalledWith("change_target_user", "For port staff");
  });

  it("hides Adjust when no redesigns are left", () => {
    mocks.state = reviewState({ allowedActions: ["approveFYPDirection"] },
                              makeFYP({ adjustments_used: 3, adjustments_left: 0 }));
    render(<FYPDirectionCard />);
    expect(screen.queryByRole("button", { name: "Adjust" })).toBeNull();
    expect(screen.getByText("You've used all 3 redesigns")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve this FYP" })).toBeTruthy();
  });

  it("shows the version and what changed for a redesign", () => {
    const fyp = makeFYP({ adjustments_used: 1, adjustments_left: 2 });
    fyp.design = { ...fyp.design!, version: 2, adjustment: "make_simpler" };
    mocks.state = reviewState({}, fyp);
    render(<FYPDirectionCard />);
    expect(screen.getByText("Version 2 · Make project simpler")).toBeTruthy();
    expect(screen.getByText("2 of 3 redesigns left")).toBeTruthy();
  });

  it("keeps the current design reviewable after a failed redesign", () => {
    mocks.state = reviewState({
      lastEventType: "fyp_design_failed",
      eventData: { kind: "adjustment", fyp: makeFYP(), message: "Your current design is unchanged." },
    });
    render(<FYPDirectionCard />);
    expect(screen.getByText("Your current design is unchanged.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve this FYP" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Adjust" })).toBeTruthy();
  });

  it("disables the buttons while Grey is busy", () => {
    mocks.isLoading = true;
    render(<FYPDirectionCard />);
    expect((screen.getByRole("button", { name: "Approve this FYP" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Adjust" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
