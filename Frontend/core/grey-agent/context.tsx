"use client";

/**
 * Grey React context.
 *
 * Product components never use this context directly — they use the
 * hooks exported from hooks.ts (useGreyUIState, useGreyActions, useGreyAgent).
 * This keeps the internal wiring invisible to the rest of the app.
 */

import { createContext, useContext } from "react";
import type { GreyEvent, GreyUIState } from "./types";
import { INITIAL_GREY_STATE } from "./types";

export type GreyContextValue = {
  state: GreyUIState;
  applyEvent: (event: GreyEvent) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  error: string | null;
  isLoading: boolean;
};

const defaultContext: GreyContextValue = {
  state: INITIAL_GREY_STATE,
  applyEvent: () => {},
  setLoading: () => {},
  setError: () => {},
  error: null,
  isLoading: false,
};

export const GreyContext = createContext<GreyContextValue>(defaultContext);

/** Internal hook — used only inside the grey-agent folder. */
export function useGreyContext(): GreyContextValue {
  return useContext(GreyContext);
}
