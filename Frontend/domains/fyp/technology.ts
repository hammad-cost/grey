/**
 * The technology plan as the frontend receives it (Release 0.10).
 * The backend sends it inside event data as `technology`. Read safely; labels only turn values into words.
 */

export type StackChoice = { area: string; choice: string; reason: string };
export type HardwareItem = {
  kind: string;
  name: string;
  purpose: string;
  essential: boolean;
  cost: string;
  alternative: string | null;
};
export type TechnologyPlan = { summary: string; stack: StackChoice[]; hardware: HardwareItem[] };
export type StoredTechnologyPlan = {
  id: string;
  status: "draft" | "approved";
  plan: TechnologyPlan;
  replans_used: number;
};
export type TechnologyView = {
  fyp_title: string;
  uses_ai: boolean;
  plan: StoredTechnologyPlan | null;
  replans_left: number;
  max_replans: number;
  can_replan: boolean;
};

export const AREA_LABELS: Record<string, string> = {
  frontend: "Frontend",
  backend: "Backend",
  database: "Database",
  ai_ml: "AI / ML",
  training: "Training",
  deployment: "Deployment",
};

export const COST_LABELS: Record<string, string> = {
  none: "Free / already owned",
  low: "Low cost",
  medium: "Medium cost",
  high: "High cost",
};

export function labelOf(labels: Record<string, string>, value: string | null): string {
  return value ? labels[value] ?? value : "";
}

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function readChoice(value: unknown): StackChoice | null {
  const c = value as StackChoice;
  return c && isText(c.area) && isText(c.choice) && isText(c.reason) ? { area: c.area, choice: c.choice, reason: c.reason } : null;
}

function readHardware(value: unknown): HardwareItem | null {
  const h = value as HardwareItem;
  if (!h || !isText(h.kind) || !isText(h.name) || !isText(h.purpose)) return null;
  return {
    kind: h.kind,
    name: h.name,
    purpose: h.purpose,
    essential: h.essential === true,
    cost: isText(h.cost) ? h.cost : "",
    alternative: isText(h.alternative) ? h.alternative : null,
  };
}

function readStored(value: unknown): StoredTechnologyPlan | null {
  const s = value as StoredTechnologyPlan;
  if (!s || !isText(s.id) || !s.plan || !isText(s.plan.summary)) return null;
  const stack = Array.isArray(s.plan.stack) ? s.plan.stack.map(readChoice) : [];
  const hardware = Array.isArray(s.plan.hardware) ? s.plan.hardware.map(readHardware) : [];
  return {
    id: s.id,
    status: s.status === "approved" ? "approved" : "draft",
    plan: {
      summary: s.plan.summary,
      stack: stack.filter((c): c is StackChoice => c !== null),
      hardware: hardware.filter((h): h is HardwareItem => h !== null),
    },
    replans_used: typeof s.replans_used === "number" ? s.replans_used : 0,
  };
}

/** The technology view from an event's data, or null if it isn't there. */
export function readTechnology(eventData?: Record<string, unknown>): TechnologyView | null {
  const v = eventData?.technology as TechnologyView | undefined;
  if (!v || !isText(v.fyp_title)) return null;
  return {
    fyp_title: v.fyp_title,
    uses_ai: v.uses_ai !== false,
    plan: readStored(v.plan),
    replans_left: typeof v.replans_left === "number" ? v.replans_left : 0,
    max_replans: typeof v.max_replans === "number" ? v.max_replans : 2,
    can_replan: v.can_replan === true,
  };
}
