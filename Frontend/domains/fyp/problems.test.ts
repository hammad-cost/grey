/**
 * Tests for the problem helpers: source-type labels and the sample-data check.
 */

import { describe, expect, it } from "vitest";
import { isSampleData, sourceTypeLabel } from "./problems";
import { makeProblem } from "./testProblems";

describe("sourceTypeLabel", () => {
  it("separates a startup's own website from a directory listing", () => {
    expect(sourceTypeLabel("startup", "A")).toBe("Startup website");
    expect(sourceTypeLabel("startup", "C")).toBe("Startup directory");
  });

  it("names the other kinds of source", () => {
    expect(sourceTypeLabel("news", "B")).toBe("News");
    expect(sourceTypeLabel("research_paper", "A")).toBe("Research paper");
    expect(sourceTypeLabel("government_report", "A")).toBe("Government report");
    expect(sourceTypeLabel("dataset", "B")).toBe("Dataset");
  });

  it("falls back to a neutral word for unknown types", () => {
    expect(sourceTypeLabel("something_new", "B")).toBe("Source");
  });
});

describe("isSampleData", () => {
  const real = (n: number) =>
    makeProblem(n, { evidence: makeProblem(n).evidence.map((s) => ({ ...s, url: `https://real-${n}.org/x` })) });

  it("is true for the fake LLM or mock (.example) sources", () => {
    expect(isSampleData([real(1)], "fake")).toBe(true);
    expect(isSampleData([makeProblem(1)], "groq")).toBe(true);
  });

  it("is false for real sources and a real LLM", () => {
    expect(isSampleData([real(1), real(2)], "groq")).toBe(false);
  });

  it("ignores malformed links instead of crashing", () => {
    const odd = makeProblem(1, { evidence: makeProblem(1).evidence.map((s) => ({ ...s, url: "not a url" })) });
    expect(isSampleData([odd], "groq")).toBe(false);
  });
});
