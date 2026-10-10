/**
 * Tests for reading the dataset recommendation from backend event data (Release 0.8).
 */

import { describe, expect, it } from "vitest";
import { isSampleDatasets, labelOf, KIND_LABELS, readDatasets, selectedOption } from "./datasets";
import { makeDatasets, OWN_DATASET, PUBLIC_DATASET } from "./testDatasets";

describe("readDatasets", () => {
  it("reads a well-formed view", () => {
    const view = readDatasets({ datasets: makeDatasets() });
    expect(view?.plan?.plan.primary).toEqual(PUBLIC_DATASET);
    expect(view?.plan?.plan.alternative).toEqual(OWN_DATASET);
    expect(view?.available_researches).toEqual(["other_options", "own_data"]);
    expect(view?.pages_found).toBe(6);
  });

  it("returns null when there is no view", () => {
    expect(readDatasets(undefined)).toBeNull();
    expect(readDatasets({ datasets: { nope: true } })).toBeNull();
  });

  it("drops a broken plan but keeps the view", () => {
    const broken = makeDatasets();
    (broken.plan as unknown as { plan: { primary: unknown } }).plan.primary = { kind: "public" };
    const view = readDatasets({ datasets: broken });
    expect(view?.fyp_title).toBe("Explainable alerts for unusual vessel movements");
    expect(view?.plan).toBeNull();
  });

  it("ignores unknown re-search options and links that aren't web addresses", () => {
    const view = readDatasets({
      datasets: makeDatasets(
        { available_researches: ["own_data", "bigger_data"] },
        { ...PUBLIC_DATASET, url: "javascript:alert(1)" }
      ),
    });
    expect(view?.available_researches).toEqual(["own_data"]);
    expect(view?.plan?.plan.primary.url).toBeNull();
  });
});

describe("helpers", () => {
  it("finds the selected option", () => {
    const plan = makeDatasets().plan!;
    expect(selectedOption(plan)).toBeNull();
    expect(selectedOption({ ...plan, status: "selected", selected: "alternative" })).toEqual(OWN_DATASET);
  });

  it("spots sample (mock) datasets", () => {
    const plan = makeDatasets().plan!.plan;
    expect(isSampleDatasets(plan)).toBe(false);
    expect(isSampleDatasets({ ...plan, primary: { ...PUBLIC_DATASET, url: "https://datasets.ml-hub.example/x" } }))
      .toBe(true);
  });

  it("turns kinds into words", () => {
    expect(labelOf(KIND_LABELS, "student_collected")).toBe("Data you collect");
    expect(labelOf(KIND_LABELS, "new_kind")).toBe("new_kind");
  });
});
