/**
 * The dataset recommendation as the frontend receives it (Release 0.8).
 *
 * The backend sends it inside event data as `datasets`
 * (dataset_options_ready, dataset_search_failed after a re-search, dataset_selected).
 * These helpers read it safely: anything malformed is skipped instead of
 * crashing the page. The labels below only turn backend values into words;
 * every decision (which re-searches are allowed, etc.) comes from the backend.
 */

export type DatasetOption = {
  kind: string;                // "public" | "synthetic" | "student_collected"
  name: string;
  source: string;
  url: string | null;          // only public datasets have a link
  size: string;
  main_features: string[];
  labels: string;
  license: string;
  relevance: string;
  preprocessing: string[];
  limitations: string[];
  fit: string;                 // "good" | "partial"
  how_to_get: string | null;   // own data only
};

export type DatasetPlan = {
  purpose: string;
  primary: DatasetOption;
  alternative: DatasetOption;
};

export type DatasetChoice = "primary" | "alternative";

export type StoredDatasetPlan = {
  id: string;
  status: "draft" | "selected";
  plan: DatasetPlan;
  researches_used: number;
  preference: string | null;
  selected: DatasetChoice | null;
};

export type DatasetView = {
  fyp_title: string;
  uses_ai: boolean;
  ai_task: string | null;
  plan: StoredDatasetPlan | null;
  searches_used: number;
  pages_found: number;
  researches_left: number;
  max_researches: number;
  available_researches: string[];
};

/** Where the data comes from, in words (blueprint §24). */
export const KIND_LABELS: Record<string, string> = {
  public: "Public dataset",
  synthetic: "Data you generate",
  student_collected: "Data you collect",
};

/** Does it fit the problem? In words (blueprint §25). */
export const FIT_LABELS: Record<string, string> = {
  good: "Good fit",
  partial: "Partial fit",
};

/** The new searches a student can ask for. Values match the backend. */
export const RESEARCH_OPTIONS: Record<string, { label: string; hint: string }> = {
  other_options: {
    label: "Find other options",
    hint: "Grey searches again and never shows the same datasets twice.",
  },
  own_data: {
    label: "I'd rather create or collect my own data",
    hint: "Grey plans data you generate or collect yourself as the main option.",
  },
};

/** The words for a backend value, or the value itself if it is new to the frontend. */
export function labelOf(labels: Record<string, string>, value: string | null): string {
  return value ? labels[value] ?? value : "";
}

/** True when the datasets come from mock search data (reserved ".example" addresses). */
export function isSampleDatasets(plan: DatasetPlan | null): boolean {
  if (!plan) return false;
  return [plan.primary, plan.alternative].some((o) => o.url !== null && /\.example(\/|$)/.test(o.url));
}

/** The option the student selected, or null. */
export function selectedOption(stored: StoredDatasetPlan | null): DatasetOption | null {
  if (!stored?.selected) return null;
  return stored.selected === "primary" ? stored.plan.primary : stored.plan.alternative;
}

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.filter(isText) : [];
}

function readOption(value: unknown): DatasetOption | null {
  const o = value as DatasetOption;
  if (!o || !isText(o.kind) || !isText(o.name) || !isText(o.relevance)) return null;
  return {
    kind: o.kind,
    name: o.name,
    source: isText(o.source) ? o.source : "",
    url: isText(o.url) && /^https?:\/\//.test(o.url) ? o.url : null,
    size: isText(o.size) ? o.size : "",
    main_features: texts(o.main_features),
    labels: isText(o.labels) ? o.labels : "",
    license: isText(o.license) ? o.license : "",
    relevance: o.relevance,
    preprocessing: texts(o.preprocessing),
    limitations: texts(o.limitations),
    fit: isText(o.fit) ? o.fit : "",
    how_to_get: isText(o.how_to_get) ? o.how_to_get : null,
  };
}

function readStored(value: unknown): StoredDatasetPlan | null {
  const s = value as StoredDatasetPlan;
  const primary = readOption(s?.plan?.primary);
  const alternative = readOption(s?.plan?.alternative);
  if (!s || !isText(s.id) || !primary || !alternative) return null;
  return {
    id: s.id,
    status: s.status === "selected" ? "selected" : "draft",
    plan: { purpose: isText(s.plan.purpose) ? s.plan.purpose : "", primary, alternative },
    researches_used: typeof s.researches_used === "number" ? s.researches_used : 0,
    preference: isText(s.preference) ? s.preference : null,
    selected: s.selected === "primary" || s.selected === "alternative" ? s.selected : null,
  };
}

/** The dataset view from an event's data, or null if it isn't there. */
export function readDatasets(eventData?: Record<string, unknown>): DatasetView | null {
  const v = eventData?.datasets as DatasetView | undefined;
  if (!v || !isText(v.fyp_title)) return null;
  return {
    fyp_title: v.fyp_title,
    uses_ai: v.uses_ai !== false,
    ai_task: isText(v.ai_task) ? v.ai_task : null,
    plan: readStored(v.plan),
    searches_used: typeof v.searches_used === "number" ? v.searches_used : 0,
    pages_found: typeof v.pages_found === "number" ? v.pages_found : 0,
    researches_left: typeof v.researches_left === "number" ? v.researches_left : 0,
    max_researches: typeof v.max_researches === "number" ? v.max_researches : 2,
    available_researches: Array.isArray(v.available_researches)
      ? v.available_researches.filter((p): p is string => isText(p) && p in RESEARCH_OPTIONS)
      : [],
  };
}
