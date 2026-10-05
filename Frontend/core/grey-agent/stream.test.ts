/**
 * Tests for readEventStream — reading newline-delimited GreyEvents.
 */

import { describe, expect, it } from "vitest";
import { readEventStream } from "./stream";
import { fakeBody } from "./testUtils";
import type { GreyEvent } from "./types";

const line = (type: string) => JSON.stringify({ type }) + "\n";

async function collect(chunks: string[]) {
  const received: string[] = [];
  const last = await readEventStream(fakeBody(chunks), (e: GreyEvent) => received.push(e.type));
  return { received, last };
}

describe("readEventStream", () => {
  it("reads one event per line, in order", async () => {
    const { received, last } = await collect([
      line("research_started") + line("searching_sources") + line("research_completed"),
    ]);
    expect(received).toEqual(["research_started", "searching_sources", "research_completed"]);
    expect(last?.type).toBe("research_completed");
  });

  it("joins a line that arrives split across chunks", async () => {
    const whole = line("sources_found");
    const { received } = await collect([whole.slice(0, 7), whole.slice(7)]);
    expect(received).toEqual(["sources_found"]);
  });

  it("reads a final line that has no newline", async () => {
    const { received } = await collect([line("research_started"), '{"type":"research_failed"}']);
    expect(received).toEqual(["research_started", "research_failed"]);
  });

  it("ignores blank lines and returns null for an empty stream", async () => {
    const { received, last } = await collect(["\n", "\n\n"]);
    expect(received).toEqual([]);
    expect(last).toBeNull();
  });
});
