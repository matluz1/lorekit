/**
 * Provider interface — decouples the app from any specific CLI tool.
 */

export interface StreamChunk {
  type: "text" | "tool_use" | "tool_result" | "error" | "system";
  content: string;
}

export type ErrorHandler = (msg: string) => void;

export interface ProviderOptions {
  systemPrompt: string;
  mcpConfig: string;
  cwd: string;
  model: string;
  sessionId?: string;
  allowedTools: string[];
  persist?: boolean;
  onError?: ErrorHandler;
}

export interface AgentProcess {
  send(message: string): AsyncIterableIterator<StreamChunk>;
  stop(): void;
  readonly sessionId: string | undefined;
  readonly alive: boolean;
}

export interface Provider {
  spawn(opts: ProviderOptions): AgentProcess;
}
