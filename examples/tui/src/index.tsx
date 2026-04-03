import React from "react";
import { render } from "ink";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import { App } from "./components/App.js";
import { ClaudeProvider } from "./providers/claude.js";
import { initLogger, flushLog } from "./logger.js";

// Resolve paths relative to project root (one level up from tui/)
const projectRoot = resolve(import.meta.dirname, "../..");
const mcpConfig = resolve(projectRoot, ".mcp.json");

let systemPrompt: string;
try {
  const shared = readFileSync(resolve(projectRoot, "guidelines", "SHARED_GUIDE.md"), "utf-8");
  const gm = readFileSync(resolve(projectRoot, "guidelines", "GM_GUIDE.md"), "utf-8");
  systemPrompt = shared + "\n\n" + gm;
} catch {
  systemPrompt = "You are a tabletop RPG game master.";
}

// CLI args: <model> [claude-session-id]
const model = process.argv[2];
const claudeSessionId = process.argv[3] || undefined;

if (!model) {
  console.error("Usage: npx tsx src/index.tsx <model> [claude-session-id]");
  process.exit(1);
}

// Initialize logger
initLogger(projectRoot);

// Start shared MCP HTTP server for NPC subprocess connections
const mcpHttpServer: ChildProcess = spawn(
  resolve(projectRoot, ".venv/bin/python"),
  ["mcp_server.py", "--http"],
  {
    cwd: projectRoot,
    stdio: "ignore",
    detached: false,
  }
);
mcpHttpServer.unref();

const provider = new ClaudeProvider();

const app = render(
  <App
    provider={provider}
    providerOpts={{
      systemPrompt,
      mcpConfig,
      cwd: projectRoot,
      model,
      sessionId: claudeSessionId,
      allowedTools: ["mcp__lorekit__*"],
      disallowedTools: [
        "mcp__lorekit__client_active_session_id",
        "mcp__lorekit__client_unsaved_turn_count",
      ],
      persist: true,
    }}
    model={model}
    sessionId={claudeSessionId}
  />,
  {
    exitOnCtrlC: true,
    maxFps: 30,
  }
);

await app.waitUntilExit();

// Flush buffered logs and kill the shared MCP HTTP server
await flushLog();
if (mcpHttpServer.pid) {
  mcpHttpServer.kill();
}
