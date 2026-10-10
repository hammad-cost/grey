/**
 * Tests for reading the AI strategy from backend events (Release 0.7).
 */

import { describe, expect, it } from "vitest";
import { labelOf, NECESSITY_LABELS, readAIStrategy } from "./aiStrategy";
import { makeAIStrategy, NO_AI_STRATEGY } from "./testAIStrategy";

describe("readAIStrategy", () => {
  it("reads a complete AI strategy view", () => {
    const view = readAIStrategy({ ai_strategy: makeAIStrategy() });
    expect(view?.fyp_title).toBe("Explainable alerts for unusual vessel movements");
    expect(view?.strategy?.strategy.necessity).toBe("traditional_ml");
    expect(view?.strategy?.strategy.primary_strategy?.approach).toBe("train_model");
    expect(view?.uses_ai).toBe(true);
    expect(view?.available_rechecks).toEqual(["without_ai", "existing_model"]);
  });

  it("reads a project without AI", () => {
    const view = readAIStrategy({ ai_strategy: makeAIStrategy({}, NO_AI_STRATEGY) });
    expect(view?.strategy?.strategy.task_type).toBeNull();
    expect(view?.strategy?.strategy.primary_strategy).toBeNull();
    expect(view?.uses_ai).toBe(false);
  });

  it("returns null when there is no AI strategy in the event", () => {
    expect(readAIStrategy({})).toBeNull();
    expect(readAIStrategy(undefined)).toBeNull();
    expect(readAIStrategy({ ai_strategy: "nonsense" })).toBeNull();
  });

  it("drops a malformed strategy or unknown re-check instead of crashing", () => {
    const broken = makeAIStrategy();
    const view = readAIStrategy({
      ai_strategy: { ...broken, strategy: { id: "ai-1", strategy: { necessity: 3 } }, available_rechecks: ["more_ai"] },
    });
    expect(view?.strategy).toBeNull();
    expect(view?.available_rechecks).toEqual([]);
  });
});

describe("labelOf", () => {
  it("turns backend values into words, and keeps unknown values as they are", () => {
    expect(labelOf(NECESSITY_LABELS, "rule_based")).toBe("A rule-based approach is better");
    expect(labelOf(NECESSITY_LABELS, "something_new")).toBe("something_new");
    expect(labelOf(NECESSITY_LABELS, null)).toBe("");
  });
});
