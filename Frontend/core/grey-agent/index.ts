/**
 * Grey UI Adapter — public API.
 *
 * Product components import ONLY from this file.
 * Never import from context.tsx, types.ts, or hooks.ts directly.
 *
 * Usage:
 *   import { GreyAgentProvider, useGreyUIState, useGreyActions } from "@/core/grey-agent";
 */

export { GreyAgentProvider } from "./GreyAgentProvider";
export { useGreyAgent, useGreyActions, useGreyUIState } from "./hooks";
export type {
  ActionName,
  GreyEvent,
  GreyUIState,
  WorkflowStatus,
  WorkspaceBrainSummary,
} from "./types";
export { Actions, INITIAL_GREY_STATE } from "./types";
