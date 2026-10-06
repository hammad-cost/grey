/**
 * The FYP design as the frontend receives it (Release 0.5).
 *
 * The backend sends it inside event data as `fyp` (fyp_direction_ready,
 * fyp_design_failed after a redesign, fyp_direction_approved) and the area
 * alone as `area` (area_classified). These helpers read it safely: anything
 * malformed is skipped instead of crashing the page.
 */

import type { ProblemSource } from "./problems";
import { isExampleAddress } from "./problems";

export type FunctionalArea = {
  functional_area: string;
  specific_area: string;
  explanation: string;
};

export type FYPDesign = {
  id: string;
  version: number;
  status: "draft" | "superseded" | "approved";
  title: string;
  summary: string;
  target_user: string;
  system_input: string;
  system_output: string;
  main_contribution: string;
  scope_reduction: string;
  adjustment: string | null;
  note: string | null;
};

export type WhyThisFYP = {
  problem_title: string;
  where_the_problem_came_from: string;
  why_it_matters: string;
  what_organizations_are_doing: string;
  organizations: string[];
  evidence: ProblemSource[];
  evidence_strength: { tier_a: number; tier_b: number; tier_c: number };
  how_grey_made_it_student_sized: string;
};

export type FYPView = {
  problem_id: string;
  problem_title: string;
  area: FunctionalArea | null;
  design: FYPDesign | null;
  why_this_fyp: WhyThisFYP | null;
  adjustments_used: number;
  adjustments_left: number;
  max_adjustments: number;
};

/** The controlled redesign options (no open brainstorming). Values match the backend. */
export const ADJUSTMENT_OPTIONS = [
  { value: "make_simpler", label: "Make project simpler" },
  { value: "change_target_user", label: "Change target user" },
  { value: "change_system_focus", label: "Change system focus" },
  { value: "reduce_complexity", label: "Reduce implementation complexity" },
] as const;

/** The longest note the backend accepts with a redesign. */
export const MAX_NOTE_LENGTH = 200;

const DESIGN_TEXT = [
  "id", "title", "summary", "target_user", "system_input", "system_output", "main_contribution", "scope_reduction",
] as const;
const WHY_TEXT = [
  "problem_title", "where_the_problem_came_from", "why_it_matters",
  "what_organizations_are_doing", "how_grey_made_it_student_sized",
] as const;

function isText(value: unknown): value is string {
  return typeof value === "string";
}

export function readArea(value: unknown): FunctionalArea | null {
  const a = value as FunctionalArea;
  return a && isText(a.functional_area) && isText(a.specific_area) && isText(a.explanation) ? a : null;
}

export function readDesign(value: unknown): FYPDesign | null {
  const d = value as FYPDesign;
  if (!d || DESIGN_TEXT.some((field) => !isText(d[field])) || typeof d.version !== "number") return null;
  return d;
}

function readWhy(value: unknown): WhyThisFYP | null {
  const w = value as WhyThisFYP;
  if (!w || WHY_TEXT.some((field) => !isText(w[field]))) return null;
  const evidence = Array.isArray(w.evidence)
    ? w.evidence.filter((s) => isText(s?.title) && isText(s?.url) && ["A", "B", "C"].includes(s?.evidence_tier))
    : [];
  return {
    ...w,
    organizations: Array.isArray(w.organizations) ? w.organizations.filter(isText) : [],
    evidence,
    evidence_strength: w.evidence_strength ?? { tier_a: 0, tier_b: 0, tier_c: 0 },
  };
}

/** The FYP view from an event's data, or null if it isn't there. */
export function readFYP(eventData?: Record<string, unknown>): FYPView | null {
  const f = eventData?.fyp as FYPView | undefined;
  if (!f || !isText(f.problem_title)) return null;
  const used = typeof f.adjustments_used === "number" ? f.adjustments_used : 0;
  const max = typeof f.max_adjustments === "number" ? f.max_adjustments : 3;
  return {
    problem_id: isText(f.problem_id) ? f.problem_id : "",
    problem_title: f.problem_title,
    area: readArea(f.area),
    design: readDesign(f.design),
    why_this_fyp: readWhy(f.why_this_fyp),
    adjustments_used: used,
    adjustments_left: typeof f.adjustments_left === "number" ? f.adjustments_left : Math.max(0, max - used),
    max_adjustments: max,
  };
}

/** True when the FYP's evidence is mock search data (reserved ".example" addresses). */
export function isSampleFYP(why: WhyThisFYP | null): boolean {
  return why !== null && why.evidence.some((source) => isExampleAddress(source.url));
}

/** A short label for the adjustment that produced a design version. */
export function adjustmentLabel(value: string | null): string | null {
  return ADJUSTMENT_OPTIONS.find((option) => option.value === value)?.label ?? null;
}
