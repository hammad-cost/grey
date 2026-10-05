/**
 * Reads a stream of GreyEvents sent by the backend.
 *
 * Some backend actions (like evidence research) take a while, so the backend
 * sends several events in one response — one JSON event per line
 * ("newline-delimited JSON"):
 *
 *   {"type":"research_started", ...}
 *   {"type":"searching_sources", ...}
 *   ...
 *
 * The network delivers the text in chunks that don't line up with lines,
 * so we keep any unfinished line in a buffer until the rest of it arrives.
 */

import type { GreyEvent } from "./types";

/**
 * Read every event from `body`, calling `onEvent` for each one as it arrives.
 * Returns the last event received (or null if the stream was empty).
 */
export async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: GreyEvent) => void
): Promise<GreyEvent | null> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lastEvent: GreyEvent | null = null;

  function handleLine(line: string) {
    if (line.trim() === "") return;
    lastEvent = JSON.parse(line) as GreyEvent;
    onEvent(lastEvent);
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? ""; // the last piece may be an unfinished line
    lines.forEach(handleLine);
  }

  // Whatever is left after the stream ends is a final line without "\n".
  handleLine(buffer + decoder.decode());
  return lastEvent;
}
