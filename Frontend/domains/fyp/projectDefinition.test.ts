/**
 * Tests for reading the project definition from backend events (Release 0.6).
 */

import { describe, expect, it } from "vitest";
import { canMove, itemsOf, readDefinition } from "./projectDefinition";
import { makeDefinition } from "./testDefinition";

describe("readDefinition", () => {
  it("reads a complete definition view", () => {
    const view = readDefinition({ definition: makeDefinition() });
    expect(view?.fyp_title).toBe("Explainable alerts for unusual vessel movements");
    expect(view?.definition?.problem_definition.gap).toBe("No simple tool explains each alert.");
    expect(view?.definition?.proposed_solution.modules).toHaveLength(2);
    expect(view?.definition?.scope).toHaveLength(6);
  });

  it("returns null when there is no definition in the event", () => {
    expect(readDefinition({})).toBeNull();
    expect(readDefinition(undefined)).toBeNull();
    expect(readDefinition({ definition: "nonsense" })).toBeNull();
  });

  it("drops a malformed definition or scope item instead of crashing", () => {
    const broken = makeDefinition();
    expect(readDefinition({ definition: { ...broken, definition: { id: 1 } } })?.definition).toBeNull();

    const withBadItem = makeDefinition();
    withBadItem.definition!.scope.push({ id: "x", title: "Bad", description: "d", kind: "maybe" as never, position: 0 });
    expect(readDefinition({ definition: withBadItem })?.definition?.scope).toHaveLength(6);
  });
});

describe("scope helpers", () => {
  it("itemsOf keeps each list in its saved order", () => {
    const scope = makeDefinition().definition!.scope;
    expect(itemsOf(scope, "out_of_scope").map((i) => i.title)).toEqual(["Live feeds", "Mobile app"]);
    expect(itemsOf([...scope].reverse(), "core").map((i) => i.id)).toEqual(["s-1", "s-2", "s-3"]);
  });

  it("canMove mirrors the backend's core limits", () => {
    const view = makeDefinition();
    const [first] = itemsOf(view.definition!.scope, "core");
    const optional = itemsOf(view.definition!.scope, "optional")[0];

    expect(canMove(view, first, "optional")).toBe(true);                    // 3 → 2 core is fine
    expect(canMove(view, first, "core")).toBe(false);                       // already there
    expect(canMove({ ...view, min_core_features: 3 }, first, "optional")).toBe(false);
    expect(canMove({ ...view, max_core_features: 3 }, optional, "core")).toBe(false);
  });
});
