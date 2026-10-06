/**
 * Tests for reading the FYP design from backend events (Release 0.5).
 */

import { describe, expect, it } from "vitest";
import { ADJUSTMENT_OPTIONS, adjustmentLabel, isSampleFYP, readArea, readFYP } from "./fypDesign";
import { makeFYP } from "./testFYP";

describe("readFYP", () => {
  it("reads a complete FYP view", () => {
    const fyp = readFYP({ fyp: makeFYP() });
    expect(fyp?.design?.title).toBe("Explainable alerts for unusual vessel movements");
    expect(fyp?.area?.functional_area).toBe("Maritime Surveillance");
    expect(fyp?.why_this_fyp?.evidence).toHaveLength(2);
    expect(fyp?.adjustments_left).toBe(3);
  });

  it("returns null when there is no FYP in the event", () => {
    expect(readFYP({})).toBeNull();
    expect(readFYP(undefined)).toBeNull();
    expect(readFYP({ fyp: "nonsense" })).toBeNull();
  });

  it("drops a malformed design or area instead of crashing", () => {
    const fyp = readFYP({ fyp: { ...makeFYP(), design: { title: 1 }, area: { functional_area: 2 } } });
    expect(fyp?.design).toBeNull();
    expect(fyp?.area).toBeNull();
  });

  it("skips malformed sources in Why this FYP", () => {
    const base = makeFYP();
    const why = { ...base.why_this_fyp!, evidence: [...base.why_this_fyp!.evidence, { title: "no url" }] };
    expect(readFYP({ fyp: { ...base, why_this_fyp: why } })?.why_this_fyp?.evidence).toHaveLength(2);
  });
});

describe("helpers", () => {
  it("offers exactly the four controlled adjustments", () => {
    expect(ADJUSTMENT_OPTIONS.map((o) => o.value)).toEqual([
      "make_simpler", "change_target_user", "change_system_focus", "reduce_complexity",
    ]);
    expect(ADJUSTMENT_OPTIONS.some((o) => /ai/i.test(o.label))).toBe(false);
  });

  it("labels the adjustment behind a version", () => {
    expect(adjustmentLabel("change_target_user")).toBe("Change target user");
    expect(adjustmentLabel(null)).toBeNull();
  });

  it("reads an area on its own", () => {
    expect(readArea(makeFYP().area)?.specific_area).toBe("Vessel Behavior Monitoring");
    expect(readArea(null)).toBeNull();
  });

  it("spots sample (mock) evidence", () => {
    expect(isSampleFYP(makeFYP().why_this_fyp)).toBe(true);
    const real = makeFYP().why_this_fyp!;
    expect(isSampleFYP({ ...real, evidence: real.evidence.map((s) => ({ ...s, url: "https://who.int/x" })) })).toBe(false);
    expect(isSampleFYP(null)).toBe(false);
  });
});
