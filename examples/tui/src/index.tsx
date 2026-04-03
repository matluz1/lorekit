// examples/tui/src/index.tsx
import React from "react";
import { render } from "ink";
import { spawn, type ChildProcess } from "node:child_process";
import { App } from "./components/App.js";
import { isServerRunning, setBaseUrl } from "./api.js";

// CLI args: [--model <model>] [--provider <provider>] [--campaign-dir <dir>] [--port <port>]
function parseArgs() {
  const args = process.argv.slice(2);
  let model: string | undefined;
  let provider: string | undefined;
  let campaignDir: string | undefined;
  let port = 8765;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--model" && args[i + 1]) {
      model = args[++i];
    } else if (args[i] === "--provider" && args[i + 1]) {
      provider = args[++i];
    } else if (args[i] === "--campaign-dir" && args[i + 1]) {
      campaignDir = args[++i];
    } else if (args[i] === "--port" && args[i + 1]) {
      port = parseInt(args[++i]!, 10);
    } else if (!args[i]!.startsWith("--") && !model) {
      // Positional arg: treat as model for backwards compat
      model = args[i];
    }
  }

  return { model, provider, campaignDir, port };
}

async function waitForServer(port: number, maxWaitMs = 10_000): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    if (await isServerRunning()) return true;
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

async function main() {
  const { model, provider, campaignDir, port } = parseArgs();
  setBaseUrl(`http://127.0.0.1:${port}`);

  let serverProc: ChildProcess | undefined;
  let weStartedServer = false;

  // Check if server is already running
  const alreadyRunning = await isServerRunning();

  if (!alreadyRunning) {
    // Auto-start lorekit serve
    // Expects `lorekit` to be installed in the active Python environment
    const serveArgs = ["serve", "--campaign-dir", campaignDir ?? ".", "--port", String(port)];
    if (model) serveArgs.push("--model", model);
    if (provider) serveArgs.push("--provider", provider);

    serverProc = spawn("lorekit", serveArgs, {
      stdio: "ignore",
      detached: false,
    });
    serverProc.unref();
    weStartedServer = true;

    const ready = await waitForServer(port);
    if (!ready) {
      console.error("Failed to connect to lorekit server after 10 seconds.");
      process.exit(1);
    }
  }

  const app = render(
    <App model={model ?? "default"} />,
    { exitOnCtrlC: true, maxFps: 30 },
  );

  await app.waitUntilExit();

  // Cleanup: kill server if we started it
  if (weStartedServer && serverProc?.pid) {
    serverProc.kill();
  }
}

main();
