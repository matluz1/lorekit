import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import type {
  Provider,
  ProviderOptions,
  AgentProcess,
  StreamChunk,
} from "../provider.js";

/**
 * Parse a single JSONL line from Claude's stream-json output into a StreamChunk.
 * Returns null for lines we want to skip (pings, internal events).
 */
function parseChunk(line: string): StreamChunk | null {
  if (!line.trim()) return null;

  let msg: any;
  try {
    msg = JSON.parse(line);
  } catch {
    return null;
  }

  // Streaming delta events
  if (msg.type === "stream_event") {
    const evt = msg.event;
    if (!evt) return null;

    if (evt.type === "content_block_start" && evt.content_block?.type === "tool_use") {
      return { type: "tool_use", content: evt.content_block.name ?? "" };
    }

    if (evt.type === "content_block_delta") {
      if (evt.delta?.type === "text_delta" && evt.delta.text) {
        return { type: "text", content: evt.delta.text };
      }
    }
    // Skip pings, message_start, content_block_stop, message_delta, message_stop, input_json_delta
    return null;
  }

  // Final result
  if (msg.type === "result") {
    if (msg.is_error) {
      const errors = msg.errors?.join("; ") ?? msg.result ?? "Unknown error";
      return { type: "error", content: errors };
    }
    return null; // Success result — text already streamed
  }

  // System init message
  if (msg.type === "system" && msg.subtype === "init") {
    return { type: "system", content: msg.session_id ?? "" };
  }

  // Tool result messages (verbose mode complete messages)
  const content = msg.content ?? msg.message?.content;
  if (Array.isArray(content)) {
    for (const block of content) {
      if (block.type === "tool_result") {
        const text = typeof block.content === "string"
          ? block.content
          : JSON.stringify(block.content);
        // Surface errors — either explicit is_error or content starting with ERROR:
        if (block.is_error || text.startsWith("ERROR:")) {
          return { type: "tool_result", content: text };
        }
      }
    }
  }

  return null;
}

export class ClaudeProvider implements Provider {
  spawn(opts: ProviderOptions): AgentProcess {
    if (opts.persist) {
      return new PersistentProcess(opts);
    }
    return new EphemeralProcess(opts);
  }
}

/** Build the base CLI args shared between persistent and ephemeral modes. */
function baseArgs(opts: ProviderOptions): string[] {
  const args = [
    "-p",
    "--verbose",
    "--output-format",
    "stream-json",
    "--include-partial-messages",
    "--model",
    opts.model,
    "--permission-mode",
    "bypassPermissions",
    "--tools",
    "",
  ];

  if (opts.mcpConfig) {
    args.push("--mcp-config", opts.mcpConfig);
  }

  if (opts.systemPrompt) {
    args.push("--system-prompt", opts.systemPrompt);
  }

  if (opts.allowedTools.length > 0) {
    args.push("--allowed-tools", ...opts.allowedTools);
  }

  return args;
}

/**
 * Persistent process for the GM — stays alive across turns.
 * Uses --input-format stream-json to send multiple messages via stdin.
 */
class PersistentProcess implements AgentProcess {
  private proc: ChildProcess;
  private rl: ReturnType<typeof createInterface>;
  private _sessionId: string | undefined;
  private lineBuffer: string[] = [];
  private waitingResolve: ((line: string | null) => void) | null = null;
  private done = false;
  private stderrChunks: string[] = [];

  constructor(private opts: ProviderOptions) {
    const args = [
      ...baseArgs(opts),
      "--input-format",
      "stream-json",
    ];

    if (opts.sessionId) {
      args.push("--session-id", opts.sessionId);
    }

    this.proc = spawn("claude", args, {
      stdio: ["pipe", "pipe", "pipe"],
      cwd: opts.cwd || undefined,
    });

    // Capture stderr for error reporting
    this.proc.stderr?.on("data", (data: Buffer) => {
      const text = data.toString().trim();
      if (text) this.stderrChunks.push(text);
    });

    this.proc.on("error", (err) => {
      this.done = true;
      this.opts.onError?.(`Failed to spawn claude: ${err.message}`);
      if (this.waitingResolve) {
        this.waitingResolve(null);
        this.waitingResolve = null;
      }
    });

    // Prevent unhandled error on stdin if process dies
    this.proc.stdin?.on("error", () => {});
    this.proc.stdout?.on("error", () => {});

    this.rl = createInterface({ input: this.proc.stdout! });

    this.rl.on("line", (line) => {
      // Capture session_id from init message
      const trimmed = line.trim();
      if (trimmed && !this._sessionId) {
        try {
          const msg = JSON.parse(trimmed);
          if (msg.type === "system" && msg.session_id) {
            this._sessionId = msg.session_id;
          }
        } catch {}
      }

      if (this.waitingResolve) {
        const resolve = this.waitingResolve;
        this.waitingResolve = null;
        resolve(line);
      } else {
        this.lineBuffer.push(line);
      }
    });

    this.rl.on("close", () => {
      this.done = true;
      if (this.waitingResolve) {
        this.waitingResolve(null);
        this.waitingResolve = null;
      }
    });

    this.proc.on("exit", (code) => {
      this.done = true;
      if (code && code !== 0) {
        const stderr = this.stderrChunks.join("\n");
        this.opts.onError?.(`claude exited with code ${code}${stderr ? ": " + stderr : ""}`);
      }
      if (this.waitingResolve) {
        this.waitingResolve(null);
        this.waitingResolve = null;
      }
    });
  }

  get sessionId() {
    return this._sessionId ?? this.opts.sessionId;
  }

  get alive() {
    return !this.done;
  }

  private nextLine(): Promise<string | null> {
    if (this.lineBuffer.length > 0) {
      return Promise.resolve(this.lineBuffer.shift()!);
    }
    if (this.done) return Promise.resolve(null);
    return new Promise((resolve) => {
      this.waitingResolve = resolve;
    });
  }

  async *send(message: string): AsyncIterableIterator<StreamChunk> {
    const userMsg = JSON.stringify({
      type: "user",
      message: { role: "user", content: message },
    });
    this.proc.stdin!.write(userMsg + "\n");

    // Read lines until we get a "result" message (end of turn)
    while (true) {
      const line = await this.nextLine();
      if (line === null) break;

      const chunk = parseChunk(line);
      if (chunk) {
        // Drip text one character at a time for smooth streaming.
        // setTimeout(0) yields to the event loop so Ink can render between chars.
        if (chunk.type === "text") {
          const text = chunk.content;
          for (let i = 0; i < text.length; i += 4) {
            yield { type: "text", content: text.slice(i, i + 4) };
            await new Promise(resolve => setImmediate(resolve));
          }
        } else {
          yield chunk;
        }
      }

      // Check if this is a result message (end of this turn)
      try {
        const msg = JSON.parse(line);
        if (msg.type === "result") break;
      } catch {}
    }
  }

  stop() {
    this.proc.stdin?.end();
    this.proc.kill();
  }
}

/**
 * Ephemeral process for NPCs — one process per interaction.
 * Message is passed as a CLI argument.
 */
class EphemeralProcess implements AgentProcess {
  private opts: ProviderOptions;
  private proc: ChildProcess | null = null;

  constructor(opts: ProviderOptions) {
    this.opts = opts;
  }

  get sessionId() {
    return undefined;
  }

  get alive() {
    return true; // ephemeral processes are always "ready" to spawn
  }

  async *send(message: string): AsyncIterableIterator<StreamChunk> {
    const args = [
      ...baseArgs(this.opts),
      "--no-session-persistence",
      message,
    ];

    this.proc = spawn("claude", args, {
      stdio: ["ignore", "pipe", "pipe"],
      cwd: this.opts.cwd || undefined,
    });

    // Capture stderr for error reporting
    const stderrChunks: string[] = [];
    this.proc.stderr?.on("data", (data: Buffer) => {
      const text = data.toString().trim();
      if (text) stderrChunks.push(text);
    });

    this.proc.stdout?.on("error", () => {});

    const rl = createInterface({ input: this.proc.stdout! });

    let gotResult = false;
    for await (const line of rl) {
      const chunk = parseChunk(line);
      if (chunk) {
        if (chunk.type === "text") {
          const text = chunk.content;
          for (let i = 0; i < text.length; i += 4) {
            yield { type: "text", content: text.slice(i, i + 4) };
            await new Promise(resolve => setImmediate(resolve));
          }
        } else {
          yield chunk;
        }
      }

      // Break on result message (end of turn) — don't wait for process close
      try {
        const msg = JSON.parse(line);
        if (msg.type === "result") {
          gotResult = true;
          break;
        }
      } catch {}
    }

    // If we never got a result, report stderr
    if (!gotResult && stderrChunks.length > 0) {
      yield { type: "error", content: stderrChunks.join("\n") };
    }

    // Clean up
    rl.close();
    this.proc.kill();
  }

  stop() {
    this.proc?.kill();
  }
}
