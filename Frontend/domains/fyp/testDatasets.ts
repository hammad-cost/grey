/**
 * A sample dataset view shaped exactly like the backend's
 * dataset_options_ready event data (`datasets`). Used only by tests.
 */

import type { DatasetOption, DatasetView } from "./datasets";

export const PUBLIC_DATASET: DatasetOption = {
  kind: "public",
  name: "Vessel AIS tracks with labelled anomalies",
  source: "Kaggle",
  url: "https://www.kaggle.com/datasets/someone/vessel-ais-anomalies",
  size: "12,000 labelled vessel tracks",
  main_features: ["Position", "Speed", "Heading"],
  labels: "Each track is marked normal or unusual",
  license: "CC BY 4.0",
  relevance: "It holds the vessel tracks the anomaly checker must score.",
  preprocessing: ["Remove duplicate positions", "Split by vessel"],
  limitations: ["Coastal waters only"],
  fit: "good",
  how_to_get: null,
};

export const OWN_DATASET: DatasetOption = {
  kind: "synthetic",
  name: "Simulated vessel tracks",
  source: "You",
  url: null,
  size: "A few thousand tracks",
  main_features: ["Position", "Speed"],
  labels: "You mark the unusual tracks",
  license: "Your own data",
  relevance: "You control which unusual patterns appear.",
  preprocessing: ["Check the tracks look realistic"],
  limitations: ["May miss patterns seen in real data"],
  fit: "partial",
  how_to_get: "Write a small simulator that adds unusual detours to normal routes.",
};

export function makeDatasets(
  overrides: Partial<DatasetView> = {},
  primary: DatasetOption = PUBLIC_DATASET,
  alternative: DatasetOption = OWN_DATASET
): DatasetView {
  return {
    fyp_title: "Explainable alerts for unusual vessel movements",
    uses_ai: true,
    ai_task: "anomaly_detection",
    plan: {
      id: "plan-1",
      status: "draft",
      plan: { purpose: "Train and test the track checker.", primary, alternative },
      researches_used: 0,
      preference: null,
      selected: null,
    },
    searches_used: 4,
    pages_found: 6,
    researches_left: 2,
    max_researches: 2,
    available_researches: ["other_options", "own_data"],
    ...overrides,
  };
}
