/**
 * StepChecklist — the "✓ done / ● active / ○ pending" list Grey shows while it works.
 *
 * Used by ResearchProgressCard and ProblemProgressCard. The steps always come
 * from the backend event (eventData.steps), never from the frontend.
 */

export type StepState = "done" | "active" | "pending";
export type ChecklistStep = { id: string; label: string; state: StepState };

/** Read the checklist from the event data, ignoring anything malformed. */
export function readSteps(eventData?: Record<string, unknown>): ChecklistStep[] {
  const value = eventData?.steps;
  if (!Array.isArray(value)) return [];
  return value.filter(
    (step): step is ChecklistStep =>
      typeof step?.id === "string" &&
      typeof step?.label === "string" &&
      ["done", "active", "pending"].includes(step?.state)
  );
}

const STEP_ICON: Record<StepState, string> = { done: "✓", active: "●", pending: "○" };
const STEP_STYLE: Record<StepState, string> = {
  done: "text-green-600",
  active: "text-accent font-medium",
  pending: "text-gray-400",
};

export function StepChecklist({ steps, label }: { steps: ChecklistStep[]; label: string }) {
  return (
    <ul className="mt-4 flex flex-col gap-1.5 text-sm" aria-label={label}>
      {steps.map((step) => (
        <li key={step.id} className={STEP_STYLE[step.state]} data-state={step.state}>
          <span className="inline-block w-5" aria-hidden="true">
            {STEP_ICON[step.state]}
          </span>
          {step.label}
        </li>
      ))}
    </ul>
  );
}
