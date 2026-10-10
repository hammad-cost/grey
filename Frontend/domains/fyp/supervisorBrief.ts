/**
 * The supervisor brief as the frontend receives it (Release 0.13).
 * The backend sends it inside event data as `supervisor_brief`. Read safely.
 */

export type ReadinessCheck = { check: string; question: string; status: string; detail: string };
export type SummaryItem = { label: string; value: string };
export type SupervisorQuestion = { id: string; question: string; talking_points: string[] };
export type SupervisorBrief = { checks: ReadinessCheck[]; summary: SummaryItem[]; questions: SupervisorQuestion[] };
export type StoredSupervisorBrief = { id: string; status: "draft" | "confirmed"; brief: SupervisorBrief };
export type SupervisorBriefView = {
  fyp_title: string;
  brief: StoredSupervisorBrief | null;
  ready: boolean | null;
  attention_count: number;
};

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function list<T>(value: unknown, read: (item: unknown) => T | null): T[] {
  return Array.isArray(value) ? value.map(read).filter((item): item is T => item !== null) : [];
}

function readCheck(value: unknown): ReadinessCheck | null {
  const c = value as ReadinessCheck;
  return c && isText(c.check) && isText(c.question) && isText(c.status) && isText(c.detail)
    ? { check: c.check, question: c.question, status: c.status, detail: c.detail } : null;
}

function readItem(value: unknown): SummaryItem | null {
  const i = value as SummaryItem;
  return i && isText(i.label) && isText(i.value) ? { label: i.label, value: i.value } : null;
}

function readQuestion(value: unknown): SupervisorQuestion | null {
  const q = value as SupervisorQuestion;
  if (!q || !isText(q.id) || !isText(q.question)) return null;
  return { id: q.id, question: q.question, talking_points: Array.isArray(q.talking_points) ? q.talking_points.filter(isText) : [] };
}

/** The supervisor brief view from an event's data, or null if it isn't there. */
export function readSupervisorBrief(eventData?: Record<string, unknown>): SupervisorBriefView | null {
  const v = eventData?.supervisor_brief as SupervisorBriefView | undefined;
  if (!v || !isText(v.fyp_title)) return null;
  const s = v.brief as StoredSupervisorBrief | null;
  const brief = s && isText(s.id) && s.brief
    ? {
        id: s.id,
        status: s.status === "confirmed" ? "confirmed" as const : "draft" as const,
        brief: {
          checks: list(s.brief.checks, readCheck),
          summary: list(s.brief.summary, readItem),
          questions: list(s.brief.questions, readQuestion),
        },
      }
    : null;
  return {
    fyp_title: v.fyp_title,
    brief,
    ready: typeof v.ready === "boolean" ? v.ready : null,
    attention_count: typeof v.attention_count === "number" ? v.attention_count : 0,
  };
}

/** The supervisor-ready summary as plain text, for copying into notes or an email. */
export function summaryAsText(title: string, brief: SupervisorBrief): string {
  return [title, "", ...brief.summary.map((i) => `${i.label}: ${i.value}`)].join("\n");
}
