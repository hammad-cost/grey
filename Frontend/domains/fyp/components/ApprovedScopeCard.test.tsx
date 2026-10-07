/**
 * Tests for ApprovedScopeCard — the end of Release 0.6.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GreyUIState } from "@/core/grey-agent";
import { makeDefinition } from "../testDefinition";
import { ApprovedScopeCard } from "./ApprovedScopeCard";

const mocks = vi.hoisted(() => ({ state: null as GreyUIState | null }));

vi.mock("@/core/grey-agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/core/grey-agent")>();
  return { ...actual, useGreyAgent: () => ({ state: mocks.state, isLoading: false, error: null }) };
});

function approvedState(overrides: Partial<GreyUIState> = {}): GreyUIState {
  const definition = makeDefinition();
  definition.definition = { ...definition.definition!, status: "approved" };
  return {
    workspaceId: "w_123",
    domain: "fyp",
    currentWorkflow: "project_definition",
    currentStage: "SCOPE_APPROVED",
    status: "complete",
    allowedActions: [],
    brainSummary: { fypTitle: "Explainable alerts for unusual vessel movements" },
    eventData: { definition },
    lastEventType: "scope_approved",
    ...overrides,
  };
}

afterEach(cleanup);

describe("ApprovedScopeCard", () => {
  it("summarises the approved scope", () => {
    mocks.state = approvedState();
    render(<ApprovedScopeCard />);

    expect(screen.getByRole("heading", { name: "Explainable alerts for unusual vessel movements" })).toBeTruthy();
    expect(within(screen.getByRole("list", { name: "Core scope" })).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText(/Plus 1 optional feature if time remains, and 2 features deliberately left out/))
      .toBeTruthy();
    expect(screen.queryAllByRole("button")).toHaveLength(0);           // nothing left to decide here
  });

  it("falls back to the Brain summary for the title", () => {
    mocks.state = approvedState({ eventData: {} });
    render(<ApprovedScopeCard />);
    expect(screen.getByRole("heading", { name: "Explainable alerts for unusual vessel movements" })).toBeTruthy();
  });

  it("shows nothing before approval", () => {
    mocks.state = approvedState({ currentStage: "SCOPE" });
    expect(render(<ApprovedScopeCard />).container.innerHTML).toBe("");
  });
});
