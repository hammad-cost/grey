/**
 * The pretrained models and APIs plan as the frontend receives it (Release 0.9).
 *
 * The backend sends it inside event data as `models` (models_ready,
 * model_search_failed after a re-search, models_approved). These helpers read
 * it safely; the labels only turn backend values into words.
 */

export type ModelOption = {
  kind: string;          // "pretrained_model" | "api_service" | "code_repository"
  name: string;
  source: string;
  url: string | null;
  use: string;           // "use_directly" | "fine_tune" | "benchmark" | "avoid"
  reason: string;
  role: string;
  limitations: string[];
};

export type ModelPlan = { needs_model: boolean; summary: string; options: ModelOption[] };

export type StoredModelPlan = {
  id: string;
  status: "draft" | "approved";
  plan: ModelPlan;
  researches_used: number;
};

export type ModelView = {
  fyp_title: string;
  ai_task: string | null;
  primary_approach: string | null;
  dataset_name: string;
  plan: StoredModelPlan | null;
  searches_used: number;
  pages_found: number;
  researches_left: number;
  max_researches: number;
  available_researches: string[];
};

export const MODEL_KIND_LABELS: Record<string, string> = {
  pretrained_model: "Pretrained model",
  api_service: "AI service / API",
  code_repository: "Code repository",
};

export const MODEL_USE_LABELS: Record<string, string> = {
  use_directly: "Use it directly",
  fine_tune: "Fine-tune it",
  benchmark: "Use it as a benchmark",
  avoid: "Avoid it",
};

export const MODEL_RESEARCH_OPTIONS: Record<string, { label: string; hint: string }> = {
  other_options: {
    label: "Look for other models",
    hint: "Grey searches again and never shows the same pages twice.",
  },
};

export function labelOf(labels: Record<string, string>, value: string | null): string {
  return value ? labels[value] ?? value : "";
}

/** True when the options come from mock search data (reserved ".example" addresses). */
export function isSampleModels(plan: ModelPlan | null): boolean {
  return !!plan && plan.options.some((o) => o.url !== null && /\.example(\/|$)/.test(o.url));
}

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function readOption(value: unknown): ModelOption | null {
  const o = value as ModelOption;
  if (!o || !isText(o.name) || !isText(o.kind) || !isText(o.use) || !isText(o.reason)) return null;
  return {
    kind: o.kind,
    name: o.name,
    source: isText(o.source) ? o.source : "",
    url: isText(o.url) && /^https?:\/\//.test(o.url) ? o.url : null,
    use: o.use,
    reason: o.reason,
    role: isText(o.role) ? o.role : "",
    limitations: Array.isArray(o.limitations) ? o.limitations.filter(isText) : [],
  };
}

function readStored(value: unknown): StoredModelPlan | null {
  const s = value as StoredModelPlan;
  if (!s || !isText(s.id) || !s.plan || !isText(s.plan.summary)) return null;
  const options = Array.isArray(s.plan.options) ? s.plan.options.map(readOption) : [];
  return {
    id: s.id,
    status: s.status === "approved" ? "approved" : "draft",
    plan: {
      needs_model: s.plan.needs_model !== false,
      summary: s.plan.summary,
      options: options.filter((o): o is ModelOption => o !== null),
    },
    researches_used: typeof s.researches_used === "number" ? s.researches_used : 0,
  };
}

/** The model view from an event's data, or null if it isn't there. */
export function readModels(eventData?: Record<string, unknown>): ModelView | null {
  const v = eventData?.models as ModelView | undefined;
  if (!v || !isText(v.fyp_title)) return null;
  return {
    fyp_title: v.fyp_title,
    ai_task: isText(v.ai_task) ? v.ai_task : null,
    primary_approach: isText(v.primary_approach) ? v.primary_approach : null,
    dataset_name: isText(v.dataset_name) ? v.dataset_name : "",
    plan: readStored(v.plan),
    searches_used: typeof v.searches_used === "number" ? v.searches_used : 0,
    pages_found: typeof v.pages_found === "number" ? v.pages_found : 0,
    researches_left: typeof v.researches_left === "number" ? v.researches_left : 0,
    max_researches: typeof v.max_researches === "number" ? v.max_researches : 2,
    available_researches: Array.isArray(v.available_researches)
      ? v.available_researches.filter((p): p is string => isText(p) && p in MODEL_RESEARCH_OPTIONS)
      : [],
  };
}
