/**
 * A sample FYP view shaped exactly like the backend's fyp_direction_ready
 * event data (`fyp`). Used only by tests.
 */

import type { FYPView } from "./fypDesign";
import { makeProblem } from "./testProblems";

export function makeFYP(overrides: Partial<FYPView> = {}): FYPView {
  const problem = makeProblem(1);
  return {
    problem_id: problem.id,
    problem_title: problem.title,
    area: {
      functional_area: "Maritime Surveillance",
      specific_area: "Vessel Behavior Monitoring",
      explanation: "The problem is about how ships move.",
    },
    design: {
      id: "d-1",
      version: 1,
      status: "draft",
      title: "Explainable alerts for unusual vessel movements",
      summary: "A web tool that flags unusual vessel tracks and explains each alert.",
      target_user: "Coastal monitoring analysts",
      system_input: "Vessel position reports over time",
      system_output: "A ranked list of unusual tracks with reasons",
      main_contribution: "Alerts an analyst can check in seconds.",
      scope_reduction: "One student builds only the alerting part of a surveillance system.",
      adjustment: null,
      note: null,
    },
    why_this_fyp: {
      problem_title: problem.title,
      where_the_problem_came_from: problem.real_world_problem,
      why_it_matters: problem.why_it_matters,
      what_organizations_are_doing: problem.observed_solutions,
      organizations: problem.evidence.map((s) => s.organization),
      evidence: problem.evidence,
      evidence_strength: problem.evidence_strength,
      how_grey_made_it_student_sized: "One student builds only the alerting part of a surveillance system.",
    },
    adjustments_used: 0,
    adjustments_left: 3,
    max_adjustments: 3,
    ...overrides,
  };
}
