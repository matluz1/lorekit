// examples/tui/src/index.tsx
import React from "react";
import { render } from "ink";
import { execSync, spawn, type ChildProcess } from "node:child_process";
import { App } from "./components/App.js";
import { setBaseUrl } from "./api.js";

const DEFAULT_PORT = 8765;

function hasCommand(cmd: string): boolean {
  try {
    execSync(`which ${cmd}`, { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

function killExisting() {
  try { execSync("pkill -f 'lorekit.server'", { stdio: "ignore" }); } catch {}
  try { execSync("pkill -f 'lorekit.http_server'", { stdio: "ignore" }); } catch {}
}

async function waitForServer(maxWaitMs = 30_000): Promise<boolean> {
  const { isServerRunning } = await import("./api.js");
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    if (await isServerRunning()) return true;
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

async function main() {
  setBaseUrl(`http://127.0.0.1:${DEFAULT_PORT}`);

  // Always start fresh
  killExisting();

  const [cmd, args] = hasCommand("lorekit")
    ? ["lorekit", ["serve"]]
    : ["uv", ["run", "lorekit", "serve"]];

  const serverProc = spawn(cmd, args, {
    stdio: ["ignore", "ignore", "pipe"],
    detached: true,
  });
  serverProc.unref();

  // Capture stderr to show config errors
  let stderr = "";
  serverProc.stderr?.on("data", (data: Buffer) => {
    stderr += data.toString();
  });

  serverProc.on("exit", (code) => {
    if (code && code !== 0) {
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
    if (serverProc.exitCode !== null) process.exit(1);
    console.error("Failed to connect to lorekit server after 30 seconds.");
    process.exit(1);
  }

  // Kill everything on exit
  function cleanup() {
    try { process.kill(-serverProc.pid!, "SIGTERM"); } catch {}
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
