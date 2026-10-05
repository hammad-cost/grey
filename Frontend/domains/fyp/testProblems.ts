/**
 * Sample problem options shaped exactly like the backend's problem_options_ready
 * event. Used only by tests.
 */

import type { ProblemOption } from "./problems";

export function makeProblem(n: number, overrides: Partial<ProblemOption> = {}): ProblemOption {
  return {
    id: `p-${n}`,
    rank: n,
    title: `Problem ${n}: abnormal vessel movement detection`,
    real_world_problem: `Operators review vessel data by hand (${n}).`,
    observed_solutions: `Companies build monitoring platforms (${n}).`,
    technical_problem: "Anomaly detection on trajectories.",
    task_type: "anomaly_detection",
    why_it_matters: `Earlier detection improves safety (${n}).`,
    possible_fyp_direction: `Flag unusual tracks in public AIS data (${n}).`,
    evidence: [
      {
        evidence_source_id: `ev-${n}-a`,
        supporting_point: "Operators review vessel tracking data manually.",
        title: `Maritime monitoring report ${n}`,
        organization: "Harbor Systems (sample company)",
        url: `https://harbor-${n}.example/report`,
        source_type: "company",
        evidence_tier: "A",
        published_date: "2026-03-01",
      },
      {
        evidence_source_id: `ev-${n}-b`,
        supporting_point: "Coastal agencies fund automated monitoring.",
        title: `Coastal programme ${n}`,
        organization: "Coastal Agency (sample government)",
        url: `https://coastal-${n}.example/programme`,
        source_type: "government_initiative",
        evidence_tier: "B",
        published_date: null,
      },
    ],
    evidence_strength: { tier_a: 1, tier_b: 1, tier_c: 0 },
    ...overrides,
  };
}
