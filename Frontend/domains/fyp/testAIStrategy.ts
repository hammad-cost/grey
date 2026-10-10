/**
 * A sample AI strategy view shaped exactly like the backend's
 * ai_strategy_ready event data (`ai_strategy`). Used only by tests.
 */

import type { AIStrategy, AIStrategyView } from "./aiStrategy";

export const ML_STRATEGY: AIStrategy = {
  necessity: "traditional_ml",
  necessity_reason: "Unusual tracks are hard to describe with fixed rules.",
  without_ai: "Speed and route limits could flag some tracks, but would miss new patterns.",
  ai_component: "The track checker that scores how unusual each track is.",
  non_ai_components: ["Report upload", "Alert list"],
  task_type: "anomaly_detection",
  primary_strategy: { approach: "train_model", reason: "Public track data is enough to train on." },
  fallback_strategy: { approach: "hybrid", reason: "Rules plus a small model if training is weak." },
};

export const NO_AI_STRATEGY: AIStrategy = {
  necessity: "rule_based",
  necessity_reason: "Clear limits describe the unusual tracks well.",
  without_ai: "Speed and route rules flag the tracks.",
  ai_component: null,
  non_ai_components: ["Report upload", "Rule checker", "Alert list"],
  task_type: null,
  primary_strategy: null,
  fallback_strategy: null,
};

export function makeAIStrategy(
  overrides: Partial<AIStrategyView> = {},
  strategy: AIStrategy = ML_STRATEGY
): AIStrategyView {
  return {
    fyp_title: "Explainable alerts for unusual vessel movements",
    core_features: ["Report upload", "Track checking", "Alert list"],
    strategy: { id: "ai-1", status: "draft", strategy, rechecks_used: 0, preference: null },
    uses_ai: strategy.necessity !== "rule_based",
    rechecks_left: 2,
    max_rechecks: 2,
    available_rechecks: strategy.necessity === "rule_based" ? [] : ["without_ai", "existing_model"],
    ...overrides,
  };
}
