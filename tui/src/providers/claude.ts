import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import type {
  Provider,
  ProviderOptions,
  AgentProcess,
  StreamChunk,
} from "../provider.js";
import { gmLog } from "../logger.js";

// ── Module-level regex constants (compiled once) ────────────
const NPC_TOOLS_RE = /^\[NPC_TOOLS:([^:]+):([^\]]+)\]/;

// ── Streaming log buffers ───────────────────────────────────
// Array-based to avoid O(n²) string concatenation.
let argsParts: string[] = [];
let thinkParts: string[] = [];
let currentBlockType = "";

const MAX_LINE_BUFFER = 2000;

/** Log interesting events from a raw JSONL line to gm.log. */
function logStreamLine(msg: any) {
  if (msg.type === "stream_event") {
    const evt = msg.event;
    if (!evt) return;

    if (evt.type === "content_block_start") {
      const block = evt.content_block;
      currentBlockType = block?.type ?? "";
      if (block?.type === "tool_use") {
        argsParts = [];
        gmLog("TOOL", block.name ?? "");
      } else if (block?.type === "thinking") {
        thinkParts = [];
      }
    } else if (evt.type === "content_block_delta") {
      const d = evt.delta;
      if (d?.type === "thinking_delta" && d.thinking) {
        thinkParts.push(d.thinking);
      } else if (d?.type === "input_json_delta" && d.partial_json) {
        argsParts.push(d.partial_json);
      }
    } else if (evt.type === "content_block_stop") {
      if (thinkParts.length > 0) {
        gmLog("THINK", thinkParts.join(""));
        thinkParts = [];
      }
      if (argsParts.length > 0) {
        gmLog("ARGS", argsParts.join(""));
        argsParts = [];
      }
    }
  } else if (msg.type === "user") {
    const content = msg.message?.content;
    if (typeof content === "string") {
      gmLog("USER", content);
    } else if (Array.isArray(content)) {
      for (const block of content) {
        if (block.type === "tool_result") {
          let text = typeof block.content === "string"
            ? block.content
            : Array.isArray(block.content)
              ? block.content.map((c: any) => c.text ?? "").join("")
              : JSON.stringify(block.content);
          try {
            const parsed = JSON.parse(text);
            if (typeof parsed.result === "string") text = parsed.result;
          } catch {}
          gmLog("RESULT", text.slice(0, 500));
        }
      }
    }
  }
}

/**
 * Parse a single JSONL line from Claude's stream-json output.
 * Returns the parsed JSON and an optional StreamChunk.
 * Parses JSON exactly once per line.
 */
function parseLine(line: string): { msg: any; chunk: StreamChunk | null } {
  const trimmed = line.trim();
  if (!trimmed) return { msg: null, chunk: null };

  let msg: any;
  try {
    msg = JSON.parse(trimmed);
  } catch {
    return { msg: null, chunk: null };
  }

  // Streaming delta events
  if (msg.type === "stream_event") {
    const evt = msg.event;
    if (!evt) return { msg, chunk: null };

    if (evt.type === "content_block_start" && evt.content_block?.type === "tool_use") {
      return { msg, chunk: { type: "tool_use", content: evt.content_block.name ?? "" } };
    }

    if (evt.type === "content_block_delta") {
      if (evt.delta?.type === "text_delta" && evt.delta.text) {
        return { msg, chunk: { type: "text", content: evt.delta.text } };
      }
    }
    return { msg, chunk: null };
  }

  // Final result
  if (msg.type === "result") {
    if (msg.is_error) {
      const errors = msg.errors?.join("; ") ?? msg.result ?? "Unknown error";
      return { msg, chunk: { type: "error", content: errors } };
    }
    return { msg, chunk: null };
  }

  // System init message
  if (msg.type === "system" && msg.subtype === "init") {
    return { msg, chunk: { type: "system", content: msg.session_id ?? "" } };
  }

  // Tool result messages (verbose mode complete messages)
  const content = msg.content ?? msg.message?.content;
  if (Array.isArray(content)) {
    for (const block of content) {
      if (block.type === "tool_result") {
        let text = typeof block.content === "string"
          ? block.content
          : Array.isArray(block.content)
            ? block.content.map((c: any) => c.text ?? "").join("")
            : JSON.stringify(block.content);
        try {
          const parsed = JSON.parse(text);
          if (typeof parsed.result === "string") text = parsed.result;
        } catch {}
        if (block.is_error || text.startsWith("ERROR:")) {
          return { msg, chunk: { type: "tool_result", content: text } };
        }
        const npcMatch = text.match(NPC_TOOLS_RE);
        if (npcMatch) {
          return { msg, chunk: { type: "npc_tool_use", content: `${npcMatch[1]}:${npcMatch[2]}` } };
        }
      }
    }
  }

  return { msg, chunk: null };
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
    args.push("--allowedTools", ...opts.allowedTools);
  }
  if (opts.disallowedTools && opts.disallowedTools.length > 0) {
    args.push("--disallowedTools", ...opts.disallowedTools);
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
  private stderrText = "";

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

    this.proc.stderr?.on("data", (data: Buffer) => {
      const text = data.toString().trim();
      if (text) this.stderrText += text + "\n";
    });

    this.proc.on("error", (err: any) => {
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

    this.rl.on("line", (line: any) => {
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
        // Cap buffer to prevent unbounded growth
        if (this.lineBuffer.length < MAX_LINE_BUFFER) {
          this.lineBuffer.push(line);
        }
      }
    });

    this.rl.on("close", () => {
      this.done = true;
      if (this.waitingResolve) {
        this.waitingResolve(null);
        this.waitingResolve = null;
      }
    });

    this.proc.on("exit", (code: any) => {
      this.done = true;
      if (code && code !== 0) {
        this.opts.onError?.(`claude exited with code ${code}${this.stderrText ? ": " + this.stderrText : ""}`);
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
    gmLog("USER", message);

    while (true) {
      const line = await this.nextLine();
      if (line === null) break;

      const { msg, chunk } = parseLine(line);
      if (msg) logStreamLine(msg);
      if (chunk) yield chunk;
      if (msg?.type === "result") break;
    }
  }

  stop() {
    this.proc.stdin?.end();
    this.rl.close();
    this.proc.removeAllListeners();
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

    const stderrParts: string[] = [];
    this.proc.stderr?.on("data", (data: Buffer) => {
      const text = data.toString().trim();
      if (text) stderrParts.push(text);
    });

    this.proc.stdout?.on("error", () => {});

    const rl = createInterface({ input: this.proc.stdout! });

    let gotResult = false;
    for await (const line of rl) {
      const { msg, chunk } = parseLine(line);
      if (chunk) yield chunk;
      if (msg?.type === "result") {
        gotResult = true;
        break;
      }
    }

    if (!gotResult && stderrParts.length > 0) {
      yield { type: "error", content: stderrParts.join("\n") };
    }

    rl.close();
    this.proc.removeAllListeners();
    this.proc.kill();
  }

  stop() {
    this.proc?.kill();
  }
}
