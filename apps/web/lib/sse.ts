/**
 * Minimal POST-based SSE reader.
 *
 * `EventSource` only supports GET, but the chat endpoint is a POST with a
 * JSON body — so we read the `text/event-stream` manually and emit parsed
 * `{ event, data }` frames.
 */
export interface SSEEvent {
  event: string;
  data: Record<string, unknown>;
}

export async function streamSSE(
  url: string,
  body: unknown,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const j = await resp.json();
      if (j?.detail) detail = String(j.detail);
    } catch {
      /* non-JSON error */
    }
    throw new Error(detail);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const emitFrame = (raw: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of raw.split("\n")) {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }
    if (dataLines.length === 0) return;
    try {
      const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
      onEvent({ event, data });
    } catch {
      /* skip malformed frame */
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep = buffer.indexOf("\n\n");
    while (sep >= 0) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      emitFrame(frame);
      sep = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) emitFrame(buffer);
}
