/**
 * The project definition and scope as the frontend receives it (Release 0.6).
 *
 * The backend sends it inside event data as `definition`
 * (project_definition_ready, scope_updated, scope_approved). These helpers
 * read it safely: anything malformed is skipped instead of crashing the page.
 */

export type ScopeKind = "core" | "optional" | "out_of_scope";

export type ScopeItem = {
  id: string;
  title: string;
  description: string;
  kind: ScopeKind;
  position: number;
};

export type ProblemDefinition = {
  problem_statement: string;
  affected_users: string;
  why_it_matters: string;
  current_solutions: string;
  gap: string;
  what_will_be_built: string;
};

export type SolutionModule = { name: string; purpose: string };

export type ProposedSolution = {
  system_purpose: string;
  modules: SolutionModule[];
  workflow_steps: string[];
};

export type ProjectDefinition = {
  id: string;
  status: "draft" | "approved";
  problem_definition: ProblemDefinition;
  proposed_solution: ProposedSolution;
  scope: ScopeItem[];
  scope_changes: number;
};

export type DefinitionView = {
  fyp_title: string;
  target_user: string;
  system_input: string;
  system_output: string;
  definition: ProjectDefinition | null;
  min_core_features: number;
  max_core_features: number;
};

/** The three scope lists, in the order they are shown. Values match the backend. */
export const SCOPE_LISTS: { kind: ScopeKind; label: string; hint: string }[] = [
  { kind: "core", label: "Core scope", hint: "Must be built for the project to work." },
  { kind: "optional", label: "Optional scope", hint: "Added only if time remains." },
  { kind: "out_of_scope", label: "Out of scope", hint: "Intentionally left out to keep the project realistic." },
];

/** Short names for the "Move to…" buttons. */
export const MOVE_LABELS: Record<ScopeKind, string> = {
  core: "Core",
  optional: "Optional",
  out_of_scope: "Out of scope",
};

const PROBLEM_FIELDS = [
  "problem_statement", "affected_users", "why_it_matters", "current_solutions", "gap", "what_will_be_built",
] as const;
const VIEW_TEXT = ["fyp_title", "target_user", "system_input", "system_output"] as const;
const KINDS: ScopeKind[] = ["core", "optional", "out_of_scope"];

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function readItem(value: unknown): ScopeItem | null {
  const i = value as ScopeItem;
  return i && isText(i.id) && isText(i.title) && isText(i.description) && KINDS.includes(i.kind) ? i : null;
}

function readSolution(value: unknown): ProposedSolution | null {
  const s = value as ProposedSolution;
  if (!s || !isText(s.system_purpose)) return null;
  return {
    system_purpose: s.system_purpose,
    modules: Array.isArray(s.modules) ? s.modules.filter((m) => isText(m?.name) && isText(m?.purpose)) : [],
    workflow_steps: Array.isArray(s.workflow_steps) ? s.workflow_steps.filter(isText) : [],
  };
}

function readDefinitionRecord(value: unknown): ProjectDefinition | null {
  const d = value as ProjectDefinition;
  const problem = d?.problem_definition;
  if (!d || !isText(d.id) || !problem || PROBLEM_FIELDS.some((field) => !isText(problem[field]))) return null;
  const solution = readSolution(d.proposed_solution);
  if (!solution) return null;
  return {
    id: d.id,
    status: d.status === "approved" ? "approved" : "draft",
    problem_definition: problem,
    proposed_solution: solution,
    scope: Array.isArray(d.scope) ? d.scope.map(readItem).filter((i): i is ScopeItem => i !== null) : [],
    scope_changes: typeof d.scope_changes === "number" ? d.scope_changes : 0,
  };
}

/** The definition view from an event's data, or null if it isn't there. */
export function readDefinition(eventData?: Record<string, unknown>): DefinitionView | null {
  const v = eventData?.definition as DefinitionView | undefined;
  if (!v || VIEW_TEXT.some((field) => !isText(v[field]))) return null;
  return {
    fyp_title: v.fyp_title,
    target_user: v.target_user,
    system_input: v.system_input,
    system_output: v.system_output,
    definition: readDefinitionRecord(v.definition),
    min_core_features: typeof v.min_core_features === "number" ? v.min_core_features : 2,
    max_core_features: typeof v.max_core_features === "number" ? v.max_core_features : 8,
  };
}

/** The items of one scope list, in their saved order. */
export function itemsOf(scope: ScopeItem[], kind: ScopeKind): ScopeItem[] {
  return scope.filter((item) => item.kind === kind).sort((a, b) => a.position - b.position);
}

/**
 * Whether an item may move to another list. Mirrors the backend's scope rules
 * so buttons can be disabled up front; the backend still checks every move.
 */
export function canMove(view: DefinitionView, item: ScopeItem, to: ScopeKind): boolean {
  if (!view.definition || item.kind === to) return false;
  const core = itemsOf(view.definition.scope, "core").length;
  if (item.kind === "core" && core - 1 < view.min_core_features) return false;
  if (to === "core" && core + 1 > view.max_core_features) return false;
  return true;
}
