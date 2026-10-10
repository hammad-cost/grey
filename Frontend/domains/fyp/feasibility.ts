/**
 * The feasibility report as the frontend receives it (Release 0.12).
 * The backend sends it inside event data as `feasibility`. Read safely; the
 * overall rating is computed by the backend, never here.
 */

export type DimensionAssessment = {
  dimension: string;
  level: string;          // "favourable" | "moderate" | "concern"
  finding: string;
  reason: string;
  assessed_by: string;    // "facts" | "judgement"
};
export type FeasibilityRisk = { risk: string; mitigation: string };
export type FeasibilityReport = {
  summary: string;
  dimensions: DimensionAssessment[];
  main_risks: FeasibilityRisk[];
  overall: string;        // "high" | "medium" | "low"
  overall_reason: string;
};
export type StoredFeasibilityReport = { id: string; status: "draft" | "accepted"; report: FeasibilityReport };
export type FeasibilityView = {
  fyp_title: string;
  report: StoredFeasibilityReport | null;
  dimension_names: Record<string, string>;
};

export const OVERALL_LABELS: Record<string, string> = { high: "High", medium: "Medium", low: "Low" };
export const LEVEL_LABELS: Record<string, string> = {
  favourable: "Favourable",
  moderate: "Moderate",
  concern: "Concern",
};

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function readDimension(value: unknown): DimensionAssessment | null {
  const d = value as DimensionAssessment;
  if (!d || !isText(d.dimension) || !isText(d.level) || !isText(d.finding) || !isText(d.reason)) return null;
  return { dimension: d.dimension, level: d.level, finding: d.finding, reason: d.reason,
           assessed_by: isText(d.assessed_by) ? d.assessed_by : "" };
}

function readRisk(value: unknown): FeasibilityRisk | null {
  const r = value as FeasibilityRisk;
  return r && isText(r.risk) && isText(r.mitigation) ? { risk: r.risk, mitigation: r.mitigation } : null;
}

function readStored(value: unknown): StoredFeasibilityReport | null {
  const s = value as StoredFeasibilityReport;
  const r = s?.report;
  if (!s || !isText(s.id) || !r || !isText(r.summary) || !isText(r.overall)) return null;
  const dimensions = Array.isArray(r.dimensions) ? r.dimensions.map(readDimension) : [];
  const risks = Array.isArray(r.main_risks) ? r.main_risks.map(readRisk) : [];
  return {
    id: s.id,
    status: s.status === "accepted" ? "accepted" : "draft",
    report: {
      summary: r.summary,
      dimensions: dimensions.filter((d): d is DimensionAssessment => d !== null),
      main_risks: risks.filter((x): x is FeasibilityRisk => x !== null),
      overall: r.overall,
      overall_reason: isText(r.overall_reason) ? r.overall_reason : "",
    },
  };
}

/** The feasibility view from an event's data, or null if it isn't there. */
export function readFeasibility(eventData?: Record<string, unknown>): FeasibilityView | null {
  const v = eventData?.feasibility as FeasibilityView | undefined;
  if (!v || !isText(v.fyp_title)) return null;
  const names = v.dimension_names && typeof v.dimension_names === "object" ? v.dimension_names : {};
  return { fyp_title: v.fyp_title, report: readStored(v.report), dimension_names: names };
}

/** A dimension's plain name, from the backend's list (falls back to the raw value). */
export function dimensionName(view: FeasibilityView, dimension: string): string {
  const name = view.dimension_names[dimension];
  return isText(name) ? name : dimension;
}
