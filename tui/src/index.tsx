import React from "react";
import { render } from "ink";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { App } from "./components/App.js";
import { ClaudeProvider } from "./providers/claude.js";

// Resolve paths relative to project root (one level up from tui/)
const projectRoot = resolve(import.meta.dirname, "../..");
const mcpConfig = resolve(projectRoot, ".mcp.json");

let systemPrompt: string;
try {
  systemPrompt = readFileSync(
    resolve(projectRoot, "GAMEMASTER_GUIDE.md"),
    "utf-8"
  );
} catch {
  systemPrompt = "You are a tabletop RPG game master.";
}

// CLI args: <model> [session-id]
const model = process.argv[2];
if (!model) {
  console.error("Usage: npx tsx src/index.tsx <model> [session-id]");
  process.exit(1);
}
const sessionId = process.argv[3] || undefined;

// Provider setup — only place that knows about Claude Code
const provider = new ClaudeProvider();

const app = render(
  <App
    provider={provider}
    providerOpts={{
      systemPrompt,
      mcpConfig,
      model,
      sessionId,
      allowedTools: ["mcp__lorekit__*"],
      persist: true,
    }}
    model={model}
    sessionId={sessionId}
  />,
  { exitOnCtrlC: true }
);

// Keep the process alive until the user exits
await app.waitUntilExit();
