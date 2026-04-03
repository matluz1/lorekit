/**
 * Direct MCP HTTP client for player-facing commands (save/load).
 * Calls the lorekit MCP server at http://127.0.0.1:3847/mcp
 * bypassing the GM agent for immediate, deterministic actions.
 */

const MCP_URL = "http://127.0.0.1:3847/mcp";
let rpcId = 0;

async function mcpCall(tool: string, args: Record<string, unknown>): Promise<string> {
  const res = await fetch(MCP_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      method: "tools/call",
      params: { name: tool, arguments: args },
      id: ++rpcId,
    }),
  });
  const json = await res.json();
  if (json.error) {
    throw new Error(json.error.message ?? JSON.stringify(json.error));
  }
  // MCP tool results are in json.result.content[0].text
  const content = json.result?.content;
  if (Array.isArray(content) && content.length > 0) {
    return content[0].text ?? "";
  }
  return JSON.stringify(json.result ?? "");
}

let cachedSessionId: number | null = null;

async function getSessionId(): Promise<number> {
  if (cachedSessionId !== null) return cachedSessionId;
  const result = await mcpCall("client_active_session_id", {});
  const id = parseInt(result, 10);
  if (isNaN(id)) throw new Error("No active session found");
  cachedSessionId = id;
  return id;
}

export async function mcpSave(name?: string): Promise<string> {
  const sid = await getSessionId();
  const args: Record<string, unknown> = { session_id: sid };
  if (name) args.name = name;
  return mcpCall("manual_save", args);
}

export async function mcpSaveList(): Promise<string> {
  const sid = await getSessionId();
  return mcpCall("save_list", { session_id: sid });
}

export async function mcpUnsavedCount(): Promise<number> {
  const sid = await getSessionId();
  const result = await mcpCall("client_unsaved_turn_count", { session_id: sid });
  return parseInt(result, 10) || 0;
}

export async function mcpLoadSave(name: string): Promise<string> {
  const sid = await getSessionId();
  return mcpCall("save_load", { session_id: sid, name });
}
