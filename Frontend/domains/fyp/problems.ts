/**
 * Problem options as the frontend receives them (Release 0.3).
 *
 * The backend sends problems inside event data (problem_options_ready,
 * problem_selected). These helpers read them safely: anything malformed is
 * skipped instead of crashing the page.
 */

export type ProblemSource = {
  evidence_source_id: string;
  supporting_point: string;
  title: string;
  organization: string;
  url: string;
  source_type: string;
  evidence_tier: "A" | "B" | "C";
  published_date: string | null;
};

export type ProblemOption = {
  id: string;
  rank: number;
  title: string;
  real_world_problem: string;
  observed_solutions: string;
  technical_problem: string;
  task_type: string;
  why_it_matters: string;
  possible_fyp_direction: string;
  evidence: ProblemSource[];
  evidence_strength: { tier_a: number; tier_b: number; tier_c: number };
};

const TEXT_FIELDS = [
  "id", "title", "real_world_problem", "observed_solutions", "technical_problem",
  "task_type", "why_it_matters", "possible_fyp_direction",
] as const;

function isSource(value: unknown): value is ProblemSource {
  const s = value as ProblemSource;
  return (
    typeof s?.title === "string" &&
    typeof s?.organization === "string" &&
    typeof s?.url === "string" &&
    typeof s?.supporting_point === "string" &&
    ["A", "B", "C"].includes(s?.evidence_tier)
  );
}

/** One problem, or null if it is missing anything the cards need. */
export function readProblem(value: unknown): ProblemOption | null {
  const p = value as ProblemOption;
  if (!p || TEXT_FIELDS.some((field) => typeof p[field] !== "string")) return null;
  if (!Array.isArray(p.evidence)) return null;
  const strength = p.evidence_strength ?? { tier_a: 0, tier_b: 0, tier_c: 0 };
  return { ...p, evidence: p.evidence.filter(isSource), evidence_strength: strength };
}

/** The problem cards from a problem_options_ready event. */
export function readProblems(eventData?: Record<string, unknown>): ProblemOption[] {
  const value = eventData?.problems;
  if (!Array.isArray(value)) return [];
  return value.map(readProblem).filter((p): p is ProblemOption => p !== null);
}

/** Human-friendly names for the backend's task types. */
export const TASK_TYPE_LABELS: Record<string, string> = {
  anomaly_detection: "Anomaly detection",
  classification: "Classification",
  forecasting: "Forecasting",
  optimization: "Optimization",
  nlp: "Language (NLP)",
  computer_vision: "Computer vision",
  recommendation: "Recommendation",
  decision_support: "Decision support",
  other: "Other",
};

/**
 * A short, student-friendly name for a source's type (shown in View sources).
 * A "startup" source at Tier C is a directory listing, not the startup's own site.
 */
export function sourceTypeLabel(sourceType: string, tier: string): string {
  if (sourceType === "startup") return tier === "C" ? "Startup directory" : "Startup website";
  return SOURCE_TYPE_LABELS[sourceType] ?? "Source";
}

const SOURCE_TYPE_LABELS: Record<string, string> = {
  company: "Company website",
  government_initiative: "Government",
  government_report: "Government report",
  official_program: "Official programme",
  news: "News",
  research_paper: "Research paper",
  university_research: "University research",
  public_challenge: "Public challenge",
  open_source: "Open source",
  dataset: "Dataset",
  industry_report: "Industry report",
  other: "Other source",
};

/**
 * True when the problems were made from sample data: the fake LLM, or mock
 * search results (which always use reserved ".example" web addresses).
 */
export function isSampleData(problems: ProblemOption[], provider?: unknown): boolean {
  return provider === "fake" || problems.some((p) => p.evidence.some((s) => isExampleAddress(s.url)));
}

function isExampleAddress(url: string): boolean {
  try {
    return new URL(url).hostname.endsWith(".example");
  } catch {
    return false;
  }
}
