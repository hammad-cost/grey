/**
 * The AI necessity check and AI strategy as the frontend receives it (Release 0.7).
 *
 * The backend sends it inside event data as `ai_strategy`
 * (ai_strategy_ready, ai_strategy_failed after a re-check, ai_strategy_approved).
 * These helpers read it safely: anything malformed is skipped instead of
 * crashing the page. The labels below only turn backend values into words;
 * every decision (which re-checks are allowed, etc.) comes from the backend.
 */

export type StrategyChoice = { approach: string; reason: string };

export type AIStrategy = {
  necessity: string;
  necessity_reason: string;
  without_ai: string;
  ai_component: string | null;
  non_ai_components: string[];
  task_type: string | null;
  primary_strategy: StrategyChoice | null;
  fallback_strategy: StrategyChoice | null;
};

export type StoredAIStrategy = {
  id: string;
  status: "draft" | "approved";
  strategy: AIStrategy;
  rechecks_used: number;
  preference: string | null;
};

export type AIStrategyView = {
  fyp_title: string;
  core_features: string[];
  strategy: StoredAIStrategy | null;
  uses_ai: boolean | null;
  rechecks_left: number;
  max_rechecks: number;
  available_rechecks: string[];
};

/** Grey's verdict, in words (blueprint §22). */
export const NECESSITY_LABELS: Record<string, string> = {
  ai_necessary: "AI is necessary",
  ai_optional: "AI is useful but optional",
  traditional_ml: "Traditional machine learning is enough",
  rule_based: "A rule-based approach is better",
  optimization: "Optimization fits better than AI",
  existing_model: "An existing model or service is enough",
  not_required: "AI is not required",
};

/** The AI task, in words (blueprint §23). */
export const TASK_LABELS: Record<string, string> = {
  classification: "Classification",
  regression: "Regression",
  forecasting: "Forecasting",
  anomaly_detection: "Anomaly detection",
  computer_vision: "Computer vision",
  object_detection: "Object detection",
  nlp: "Natural language processing",
  recommendation: "Recommendation",
  clustering: "Clustering",
  time_series_analysis: "Time-series analysis",
  retrieval: "Retrieval",
  generative_ai: "Generative AI",
};

/** How the AI part is built, in words (blueprint §23). */
export const APPROACH_LABELS: Record<string, string> = {
  train_model: "Train a model",
  fine_tune: "Fine-tune an existing model",
  pretrained_model: "Use a pretrained model",
  use_api: "Use an API",
  hybrid: "Hybrid approach",
};

/** The re-checks a student can ask for. Values match the backend. */
export const RECHECK_OPTIONS: Record<string, { label: string; hint: string }> = {
  without_ai: {
    label: "Can I do this without AI?",
    hint: "Grey checks again whether a non-AI approach would work.",
  },
  existing_model: {
    label: "Use a ready-made model instead",
    hint: "Grey checks whether a pretrained model or a service would be enough.",
  },
};

/** The words for a backend value, or the value itself if it is new to the frontend. */
export function labelOf(labels: Record<string, string>, value: string | null): string {
  return value ? labels[value] ?? value : "";
}

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function readChoice(value: unknown): StrategyChoice | null {
  const c = value as StrategyChoice;
  return c && isText(c.approach) && isText(c.reason) ? { approach: c.approach, reason: c.reason } : null;
}

function readStrategy(value: unknown): AIStrategy | null {
  const s = value as AIStrategy;
  if (!s || !isText(s.necessity) || !isText(s.necessity_reason) || !isText(s.without_ai)) return null;
  return {
    necessity: s.necessity,
    necessity_reason: s.necessity_reason,
    without_ai: s.without_ai,
    ai_component: isText(s.ai_component) ? s.ai_component : null,
    non_ai_components: Array.isArray(s.non_ai_components) ? s.non_ai_components.filter(isText) : [],
    task_type: isText(s.task_type) ? s.task_type : null,
    primary_strategy: readChoice(s.primary_strategy),
    fallback_strategy: readChoice(s.fallback_strategy),
  };
}

function readStored(value: unknown): StoredAIStrategy | null {
  const s = value as StoredAIStrategy;
  const strategy = readStrategy(s?.strategy);
  if (!s || !isText(s.id) || !strategy) return null;
  return {
    id: s.id,
    status: s.status === "approved" ? "approved" : "draft",
    strategy,
    rechecks_used: typeof s.rechecks_used === "number" ? s.rechecks_used : 0,
    preference: isText(s.preference) ? s.preference : null,
  };
}

/** The AI strategy view from an event's data, or null if it isn't there. */
export function readAIStrategy(eventData?: Record<string, unknown>): AIStrategyView | null {
  const v = eventData?.ai_strategy as AIStrategyView | undefined;
  if (!v || !isText(v.fyp_title)) return null;
  return {
    fyp_title: v.fyp_title,
    core_features: Array.isArray(v.core_features) ? v.core_features.filter(isText) : [],
    strategy: readStored(v.strategy),
    uses_ai: typeof v.uses_ai === "boolean" ? v.uses_ai : null,
    rechecks_left: typeof v.rechecks_left === "number" ? v.rechecks_left : 0,
    max_rechecks: typeof v.max_rechecks === "number" ? v.max_rechecks : 2,
    available_rechecks: Array.isArray(v.available_rechecks)
      ? v.available_rechecks.filter((p): p is string => isText(p) && p in RECHECK_OPTIONS)
      : [],
  };
}
