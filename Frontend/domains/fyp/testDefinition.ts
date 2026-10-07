/**
 * A sample project definition view shaped exactly like the backend's
 * project_definition_ready event data (`definition`). Used only by tests.
 */

import type { DefinitionView, ScopeItem, ScopeKind } from "./projectDefinition";

function item(id: string, title: string, kind: ScopeKind, position: number): ScopeItem {
  return { id, title, description: `${title} for the analyst.`, kind, position };
}

export function makeDefinition(overrides: Partial<DefinitionView> = {}): DefinitionView {
  return {
    fyp_title: "Explainable alerts for unusual vessel movements",
    target_user: "Coastal monitoring analysts",
    system_input: "Vessel position reports over time",
    system_output: "A ranked list of unusual tracks with reasons",
    definition: {
      id: "def-1",
      status: "draft",
      problem_definition: {
        problem_statement: "Analysts miss unusual vessel movements in large volumes of data.",
        affected_users: "Coastal monitoring analysts",
        why_it_matters: "Missed movements delay responses.",
        current_solutions: "Large monitoring platforms exist but are complex.",
        gap: "No simple tool explains each alert.",
        what_will_be_built: "A web tool that flags unusual tracks and explains them.",
      },
      proposed_solution: {
        system_purpose: "Help analysts spot and understand unusual vessel movements.",
        modules: [
          { name: "Data upload", purpose: "Load position reports." },
          { name: "Alert view", purpose: "Show unusual tracks with reasons." },
        ],
        workflow_steps: ["Upload reports", "The tool checks each track", "The analyst reviews alerts"],
      },
      scope: [
        item("s-1", "Report upload", "core", 0),
        item("s-2", "Track checking", "core", 1),
        item("s-3", "Alert list", "core", 2),
        item("s-4", "Report export", "optional", 0),
        item("s-5", "Live feeds", "out_of_scope", 0),
        item("s-6", "Mobile app", "out_of_scope", 1),
      ],
      scope_changes: 0,
    },
    min_core_features: 2,
    max_core_features: 8,
    ...overrides,
  };
}
