/**
 * Tests for ProblemOpportunityCard — one problem the student can choose.
 * A plain component: no Grey adapter is involved.
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeProblem } from "../testProblems";
import { ProblemOpportunityCard } from "./ProblemOpportunityCard";

afterEach(cleanup);

describe("ProblemOpportunityCard", () => {
  it("shows the problem, why it matters, the FYP direction and its evidence strength", () => {
    render(<ProblemOpportunityCard problem={makeProblem(1)} onChoose={vi.fn()} />);

    expect(screen.getByRole("heading", { name: /Problem 1: abnormal vessel movement detection/ })).toBeTruthy();
    expect(screen.getByText("Operators review vessel data by hand (1).")).toBeTruthy();
    expect(screen.getByText("Earlier detection improves safety (1).")).toBeTruthy();
    expect(screen.getByText("Flag unusual tracks in public AIS data (1).")).toBeTruthy();
    expect(screen.getByText("Anomaly detection")).toBeTruthy();
    expect(screen.getByText("Tier A × 1")).toBeTruthy();
    expect(screen.getByText("Tier B × 1")).toBeTruthy();
    expect(screen.queryByText(/Tier C/)).toBeNull();
  });

  it("hides the sources until 'View sources' is clicked", () => {
    render(<ProblemOpportunityCard problem={makeProblem(1)} onChoose={vi.fn()} />);
    expect(screen.queryByRole("list", { name: "Sources" })).toBeNull();

    const toggle = screen.getByRole("button", { name: "View sources (2)" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);

    expect(screen.getByRole("button", { name: "Hide sources" }).getAttribute("aria-expanded")).toBe("true");
    const sources = within(screen.getByRole("list", { name: "Sources" })).getAllByRole("listitem");
    expect(sources).toHaveLength(2);
    expect(screen.getByText("Companies build monitoring platforms (1).")).toBeTruthy();
  });

  it("shows each source's title, organization, date, tier and supporting point, with a safe link", () => {
    render(<ProblemOpportunityCard problem={makeProblem(1)} onChoose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "View sources (2)" }));

    const link = screen.getByRole("link", { name: "Maritime monitoring report 1" });
    expect(link.getAttribute("href")).toBe("https://harbor-1.example/report");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(screen.getByText("Company website · Harbor Systems (sample company) · 2026-03-01")).toBeTruthy();
    expect(screen.getByText("Government · Coastal Agency (sample government)")).toBeTruthy();   // no date
    expect(screen.getByText("“Operators review vessel tracking data manually.”")).toBeTruthy();
  });

  it("calls onChoose with the problem", () => {
    const onChoose = vi.fn();
    const problem = makeProblem(2);
    render(<ProblemOpportunityCard problem={problem} onChoose={onChoose} />);

    fireEvent.click(screen.getByRole("button", { name: "Choose this problem" }));
    expect(onChoose).toHaveBeenCalledWith(problem);
  });

  it("cannot be chosen while disabled", () => {
    const onChoose = vi.fn();
    render(<ProblemOpportunityCard problem={makeProblem(1)} onChoose={onChoose} disabled />);

    const button = screen.getByRole("button", { name: "Choose this problem" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(onChoose).not.toHaveBeenCalled();
  });

  it("labels a startup's own website differently from a directory listing", () => {
    const problem = makeProblem(1);
    problem.evidence = [
      { ...problem.evidence[0], source_type: "startup", evidence_tier: "A", organization: "Harbor AI" },
      { ...problem.evidence[1], source_type: "startup", evidence_tier: "C", organization: "Y Combinator" },
    ];
    render(<ProblemOpportunityCard problem={problem} onChoose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "View sources (2)" }));

    expect(screen.getByText(/^Startup website · Harbor AI/)).toBeTruthy();
    expect(screen.getByText(/^Startup directory · Y Combinator/)).toBeTruthy();
  });
});
