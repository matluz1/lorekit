// examples/tui/src/api.ts
/**
 * HTTP client for lorekit serve.
 *
 * sendMessage()  → POST /message, returns async iterator of GameEvents (SSE)
 * sendCommand()  → POST /command, returns result string (JSON)
 */

const DEFAULT_BASE = "http://127.0.0.1:8765";

let baseUrl = DEFAULT_BASE;

export function setBaseUrl(url: string) {
  baseUrl = url;
}

// -- Types --

export interface GameEvent {
  type: "narration" | "narration_delta" | "tool_activity" | "npc_activity" | "error" | "system";
  content: string;
}

// -- Message endpoint (SSE) --

export async function* sendMessage(text: string, verbose = true): AsyncGenerator<GameEvent> {
  const res = await fetch(`${baseUrl}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, verbose }),
  });

  if (!res.ok) {
    yield { type: "error", content: `Server error: ${res.status} ${res.statusText}` };
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    yield { type: "error", content: "No response body" };
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const event: GameEvent = JSON.parse(line.slice(6));
        yield event;
      } catch {
        // skip malformed SSE lines
      }
    }
  }
}

// -- Command endpoint (JSON) --

let cachedSessionId: number | null = null;

async function getSessionId(): Promise<number> {
  if (cachedSessionId !== null) return cachedSessionId;
  const result = await sendCommand("client_active_session_id", {});
  const id = parseInt(result, 10);
  if (isNaN(id)) throw new Error("No active session found");
  cachedSessionId = id;
  return id;
}

export async function sendCommand(cmd: string, args: Record<string, unknown>): Promise<string> {
  const res = await fetch(`${baseUrl}/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cmd, ...args }),
  });
  const json = await res.json();
  if (json.error) throw new Error(json.error);
  return json.result ?? JSON.stringify(json);
}

export async function save(name?: string): Promise<string> {
  const sid = await getSessionId();
  const args: Record<string, unknown> = { session_id: sid };
  if (name) args.name = name;
  return sendCommand("manual_save", args);
}

export async function saveList(): Promise<string> {
  const sid = await getSessionId();
  return sendCommand("save_list", { session_id: sid });
}

export async function loadSave(name: string): Promise<string> {
  const sid = await getSessionId();
  return sendCommand("save_load", { session_id: sid, name });
}

export async function unsavedCount(): Promise<number> {
  const sid = await getSessionId();
  const result = await sendCommand("client_unsaved_turn_count", { session_id: sid });
  return parseInt(result, 10) || 0;
}

// -- Lifecycle events (GET /events SSE) --

export async function* listenEvents(signal?: AbortSignal): AsyncGenerator<GameEvent> {
  const res = await fetch(`${baseUrl}/events`, { signal });
  if (!res.ok) return;

  const reader = res.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const event: GameEvent = JSON.parse(line.slice(6));
        yield event;
      } catch {
        // skip malformed
      }
    }
  }
}

// -- Server health check --

export async function isServerRunning(): Promise<boolean> {
  try {
    const res = await fetch(`${baseUrl}/events`, {
      signal: AbortSignal.timeout(2000),
    });
    // Any response means server is up (SSE streams return 200)
    res.body?.cancel();
    return true;
  } catch {
    return false;
  }
}
