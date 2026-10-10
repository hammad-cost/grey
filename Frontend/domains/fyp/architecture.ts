/**
 * The architecture and evaluation plan as the frontend receives it (Release 0.11).
 * The backend sends it inside event data as `technical_plan`. Read safely; labels only turn values into words.
 */

export type ArchitectureComponent = { id: string; name: string; kind: string; role: string; technology: string | null };
export type ArchitectureFlow = { source: string; target: string; data: string };
export type EvaluationMetric = { metric: string; why: string; goal: string };
export type SystemTest = { kind: string; how: string };
export type TechnicalPlan = {
  summary: string;
  architecture: { components: ArchitectureComponent[]; flows: ArchitectureFlow[] };
  evaluation: { metrics: EvaluationMetric[]; tests: SystemTest[]; baseline: string | null };
};
export type StoredTechnicalPlan = { id: string; status: "draft" | "approved"; plan: TechnicalPlan; redesigns_used: number };
export type TechnicalPlanView = {
  fyp_title: string;
  uses_ai: boolean;
  ai_task: string | null;
  plan: StoredTechnicalPlan | null;
  redesigns_left: number;
  max_redesigns: number;
  can_redesign: boolean;
};

export const COMPONENT_KIND_LABELS: Record<string, string> = {
  data_source: "Data",
  processing: "Processing",
  model: "AI model",
  rules: "Rules",
  backend: "Backend",
  storage: "Storage",
  interface: "Interface",
  user: "User",
  external_service: "External service",
};

export const METRIC_LABELS: Record<string, string> = {
  accuracy: "Accuracy",
  precision: "Precision",
  recall: "Recall",
  f1_score: "F1-score",
  auc: "AUC",
  mae: "MAE",
  rmse: "RMSE",
  false_alarm_rate: "False alarm rate",
  detection_rate: "Detection rate",
};

export const TEST_LABELS: Record<string, string> = {
  functional_testing: "Functional testing",
  usability_testing: "Usability testing",
  response_time: "Response time",
  baseline_comparison: "Baseline comparison",
  user_evaluation: "User evaluation",
};

export function labelOf(labels: Record<string, string>, value: string | null): string {
  return value ? labels[value] ?? value : "";
}

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function list<T>(value: unknown, read: (item: unknown) => T | null): T[] {
  return Array.isArray(value) ? value.map(read).filter((item): item is T => item !== null) : [];
}

function readComponent(value: unknown): ArchitectureComponent | null {
  const c = value as ArchitectureComponent;
  if (!c || !isText(c.id) || !isText(c.name) || !isText(c.kind) || !isText(c.role)) return null;
  return { id: c.id, name: c.name, kind: c.kind, role: c.role, technology: isText(c.technology) ? c.technology : null };
}

function readFlow(value: unknown): ArchitectureFlow | null {
  const f = value as ArchitectureFlow;
  return f && isText(f.source) && isText(f.target) && isText(f.data) ? { source: f.source, target: f.target, data: f.data } : null;
}

function readMetric(value: unknown): EvaluationMetric | null {
  const m = value as EvaluationMetric;
  return m && isText(m.metric) && isText(m.why) && isText(m.goal) ? { metric: m.metric, why: m.why, goal: m.goal } : null;
}

function readTest(value: unknown): SystemTest | null {
  const t = value as SystemTest;
  return t && isText(t.kind) && isText(t.how) ? { kind: t.kind, how: t.how } : null;
}

function readStored(value: unknown): StoredTechnicalPlan | null {
  const s = value as StoredTechnicalPlan;
  const plan = s?.plan;
  if (!s || !isText(s.id) || !plan || !isText(plan.summary) || !plan.architecture || !plan.evaluation) return null;
  return {
    id: s.id,
    status: s.status === "approved" ? "approved" : "draft",
    plan: {
      summary: plan.summary,
      architecture: {
        components: list(plan.architecture.components, readComponent),
        flows: list(plan.architecture.flows, readFlow),
      },
      evaluation: {
        metrics: list(plan.evaluation.metrics, readMetric),
        tests: list(plan.evaluation.tests, readTest),
        baseline: isText(plan.evaluation.baseline) ? plan.evaluation.baseline : null,
      },
    },
    redesigns_used: typeof s.redesigns_used === "number" ? s.redesigns_used : 0,
  };
}

/** The technical plan view from an event's data, or null if it isn't there. */
export function readTechnicalPlan(eventData?: Record<string, unknown>): TechnicalPlanView | null {
  const v = eventData?.technical_plan as TechnicalPlanView | undefined;
  if (!v || !isText(v.fyp_title)) return null;
  return {
    fyp_title: v.fyp_title,
    uses_ai: v.uses_ai !== false,
    ai_task: isText(v.ai_task) ? v.ai_task : null,
    plan: readStored(v.plan),
    redesigns_left: typeof v.redesigns_left === "number" ? v.redesigns_left : 0,
    max_redesigns: typeof v.max_redesigns === "number" ? v.max_redesigns : 2,
    can_redesign: v.can_redesign === true,
  };
}

/** The components in the order data reaches them (following the flows from the first one), for the diagram. */
export function pipelineOrder(plan: TechnicalPlan): ArchitectureComponent[] {
  const { components, flows } = plan.architecture;
  const byId = new Map(components.map((c) => [c.id, c]));
  const targets = new Set(flows.map((f) => f.target));
  const ordered: ArchitectureComponent[] = [];
  const seen = new Set<string>();
  const visit = (id: string) => {
    if (seen.has(id) || !byId.has(id)) return;
    seen.add(id);
    ordered.push(byId.get(id)!);
    flows.filter((f) => f.source === id).forEach((f) => visit(f.target));
  };
  components.filter((c) => !targets.has(c.id)).forEach((c) => visit(c.id));
  components.forEach((c) => visit(c.id));   // anything left (e.g. a loop back to the start)
  return ordered;
}
