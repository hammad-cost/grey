/**
 * A sample model view shaped exactly like the backend's models_ready event data (`models`). Tests only.
 */

import type { ModelOption, ModelView } from "./models";

export const FINE_TUNE_MODEL: ModelOption = {
  kind: "pretrained_model",
  name: "vessel-track-anomaly",
  source: "huggingface.co",
  url: "https://huggingface.co/someone/vessel-track-anomaly",
  use: "fine_tune",
  reason: "A close match; fine-tune it on your dataset.",
  role: "The track checker",
  limitations: ["Trained on another region"],
};

export const BENCHMARK_CODE: ModelOption = {
  kind: "code_repository",
  name: "ais-anomaly",
  source: "github.com",
  url: "https://github.com/someone/ais-anomaly",
  use: "benchmark",
  reason: "Compare your own model against it.",
  role: "Evaluation",
  limitations: ["Old code"],
};

export function makeModels(overrides: Partial<ModelView> = {}, options: ModelOption[] = [FINE_TUNE_MODEL, BENCHMARK_CODE]): ModelView {
  return {
    fyp_title: "Explainable alerts for unusual vessel movements",
    ai_task: "anomaly_detection",
    primary_approach: "train_model",
    dataset_name: "Vessel AIS tracks",
    plan: {
      id: "m-1",
      status: "draft",
      plan: { needs_model: true, summary: "Fine-tune the first model and compare against the code.", options },
      researches_used: 0,
    },
    searches_used: 4,
    pages_found: 7,
    researches_left: 2,
    max_researches: 2,
    available_researches: ["other_options"],
    ...overrides,
  };
}
