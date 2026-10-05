/**
 * Helpers shared by the grey-agent tests. Not used by the app.
 */

/** A fake response body that delivers the given text chunks one by one. */
export function fakeBody(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    getReader: () => ({
      read: async () =>
        index < chunks.length
          ? { done: false, value: encoder.encode(chunks[index++]) }
          : { done: true, value: undefined },
    }),
  } as unknown as ReadableStream<Uint8Array>;
}
