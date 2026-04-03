// examples/tui/src/index.tsx
import React from "react";
import { render } from "ink";
import { spawn, type ChildProcess } from "node:child_process";
import { App } from "./components/App.js";
import { isServerRunning, setBaseUrl } from "./api.js";

const DEFAULT_PORT = 8765;

async function waitForServer(maxWaitMs = 10_000): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    if (await isServerRunning()) return true;
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

async function main() {
  setBaseUrl(`http://127.0.0.1:${DEFAULT_PORT}`);

  let serverProc: ChildProcess | undefined;
  let weStartedServer = false;

  // Check if server is already running
  const alreadyRunning = await isServerRunning();

  if (!alreadyRunning) {
    // Auto-start lorekit serve — all config comes from ~/.config/lorekit/config.toml
    serverProc = spawn("lorekit", ["serve"], {
      stdio: ["ignore", "ignore", "pipe"],
      detached: false,
    });
    serverProc.unref();
    weStartedServer = true;

    // Capture stderr to show config errors
    let stderr = "";
    serverProc.stderr?.on("data", (data: Buffer) => {
      stderr += data.toString();
    });

    serverProc.on("exit", (code) => {
      if (code && code !== 0 && !weStartedServer) return;
      if (code && code !== 0) {
        // Server failed to start — likely missing config
        const msg = stderr.includes("No provider configured")
          ? "Missing config. Create ~/.config/lorekit/config.toml with:\n\n  [agent]\n  provider = \"claude\"\n  model = \"opus\""
          : stderr.includes("No model configured")
            ? "Missing model. Add to ~/.config/lorekit/config.toml:\n\n  [agent]\n  model = \"opus\""
            : `Server failed: ${stderr.trim().split("\n").pop()}`;
        console.error(msg);
        process.exit(1);
      }
    });

    const ready = await waitForServer();
    if (!ready) {
      // Check if process already exited with an error
      if (serverProc.exitCode !== null) {
        // Error message already printed by the exit handler
        process.exit(1);
      }
      console.error("Failed to connect to lorekit server after 10 seconds.");
      process.exit(1);
    }
  }

  // Ensure server cleanup on any exit
  function cleanup() {
    if (weStartedServer && serverProc?.pid) {
      serverProc.kill();
    }
  }
  process.on("exit", cleanup);
  process.on("SIGINT", () => { cleanup(); process.exit(0); });
  process.on("SIGTERM", () => { cleanup(); process.exit(0); });

  const app = render(
    <App />,
    { exitOnCtrlC: true, maxFps: 30 },
  );

  await app.waitUntilExit();
  cleanup();
}

main();
