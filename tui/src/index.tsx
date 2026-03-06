import React from "react";
import { render } from "ink";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { App } from "./components/App.js";
import { ClaudeProvider } from "./providers/claude.js";
import { openDb, closeDb, getActiveSessions } from "./db.js";

// Resolve paths relative to project root (one level up from tui/)
const projectRoot = resolve(import.meta.dirname, "../..");
const mcpConfig = resolve(projectRoot, ".mcp.json");

let systemPrompt: string;
try {
  const shared = readFileSync(resolve(projectRoot, "SHARED_GUIDE.md"), "utf-8");
  const gm = readFileSync(resolve(projectRoot, "GAMEMASTER_GUIDE.md"), "utf-8");
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

// Open read-only DB for sidebar, auto-detect active LoreKit session
openDb(projectRoot);
const activeSessions = getActiveSessions();
const lkSessionId = activeSessions.length > 0 ? activeSessions[0]!.id : undefined;

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
      persist: true,
    }}
    model={model}
    sessionId={claudeSessionId}
    lkSessionId={lkSessionId}
  />,
  {
    exitOnCtrlC: true,
    incrementalRendering: false,
    maxFps: 60,
  }
);

await app.waitUntilExit();
closeDb();
