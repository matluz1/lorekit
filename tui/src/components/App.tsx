import React, { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { Box, Text, useApp } from "ink";
import { Chat, type ChatMessage } from "./Chat.js";
import { Input } from "./Input.js";
import type { AgentProcess, Provider, ProviderOptions } from "../provider.js";
import { clearLog } from "../logger.js";

/** A tool call logged during the current GM turn. */
export interface ToolCallEntry {
  name: string;
  ts: number;
  error?: boolean;
}

/** An NPC tool call detected during the current GM turn. */
export interface NpcToolCallEntry {
  npcName: string;
  toolName: string;
  ts: number;
}

interface AppProps {
  provider: Provider;
  providerOpts: ProviderOptions;
  model: string;
  sessionId?: string;
  lkSessionId?: number;
}

/** Strip the "mcp__lorekit__" prefix for display. */
function shortToolName(name: string): string {
  return name.replace(/^mcp__lorekit__/, "");
}

export function App({
  provider,
  providerOpts,
  model,
  sessionId,
}: AppProps) {
  const { exit } = useApp();

  // ── GM state ──────────────────────────────────────────
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "system", content: "Starting GM process…" },
  ]);
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const agentRef = useRef<AgentProcess | null>(null);

  // Ref mirror so handleSubmit never goes stale
  const isStreamingRef = useRef(false);
  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  // ── Tool call tracking ────────────────────────────────
  const [toolCalls, setToolCalls] = useState<ToolCallEntry[]>([]);
  const [npcToolCalls, setNpcToolCalls] = useState<NpcToolCallEntry[]>([]);

  // Spawn the persistent GM process on mount
  useEffect(() => {
    const onError = (msg: string) => {
      setMessages((prev) => [
        ...prev,
        { role: "system", content: `Error: ${msg}` },
      ]);
    };

    const agent = provider.spawn({ ...providerOpts, onError });
    agentRef.current = agent;

    const timer = setTimeout(() => {
      setMessages((prev) => {
        if (prev.some((m) => m.content.startsWith("Error:"))) return prev;
        return [
          ...prev,
          { role: "system", content: "GM ready. Type your action." },
        ];
      });
    }, 2000);

    return () => {
      clearTimeout(timer);
      agent.stop();
    };
  }, []);

  // Throttle streaming text updates to reduce re-renders
  const streamFlushRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingTextRef = useRef("");

  const flushStreamingText = useCallback(() => {
    setStreamingText(pendingTextRef.current);
    streamFlushRef.current = null;
  }, []);

  // ── GM submit (stable ref — no deps on isStreaming) ───
  const handleSubmit = useCallback(
    async (text: string) => {
      if (!agentRef.current || isStreamingRef.current) return;

      if (text.toLowerCase() === "/quit") {
        agentRef.current.stop();
        exit();
        return;
      }

      if (text.toLowerCase() === "/clearlog") {
        clearLog();
        setMessages((prev) => [
          ...prev,
          { role: "system", content: "Log cleared." },
        ]);
        return;
      }

      if (!agentRef.current.alive) {
        setMessages((prev) => [
          ...prev,
          { role: "player", content: text },
          {
            role: "system",
            content:
              "GM process is not running. Restart with /quit and relaunch.",
          },
        ]);
        return;
      }

      setMessages((prev) => [...prev, { role: "player", content: text }]);
      setIsStreaming(true);
      setStreamingText("");
      pendingTextRef.current = "";
      setToolCalls([]);
      setNpcToolCalls([]);

      let fullText = "";

      try {
        for await (const chunk of agentRef.current.send(text)) {
          if (chunk.type === "text") {
            fullText += chunk.content;
            pendingTextRef.current = fullText;
            if (!streamFlushRef.current) {
              streamFlushRef.current = setTimeout(flushStreamingText, 80);
            }
          } else if (chunk.type === "tool_use") {
            setToolCalls((prev) => [
              ...prev,
              { name: chunk.content, ts: Date.now() },
            ]);
          } else if (chunk.type === "tool_result") {
            setMessages((prev) => [
              ...prev,
              { role: "system", content: `Tool error: ${chunk.content}` },
            ]);
            setToolCalls((prev) => {
              if (prev.length === 0) return prev;
              const updated = [...prev];
              updated[updated.length - 1] = {
                ...updated[updated.length - 1]!,
                error: true,
              };
              return updated;
            });
          } else if (chunk.type === "npc_tool_use") {
            const [npcName, toolsCsv] = chunk.content.split(":");
            if (npcName && toolsCsv) {
              const tools = toolsCsv.split(",");
              setNpcToolCalls((prev) => [
                ...prev,
                ...tools.map((t) => ({
                  npcName,
                  toolName: t,
                  ts: Date.now(),
                })),
              ]);
            }
          } else if (chunk.type === "error") {
            setMessages((prev) => [
              ...prev,
              { role: "system", content: `Error: ${chunk.content}` },
            ]);
          }
        }

        if (fullText) {
          setMessages((prev) => [...prev, { role: "gm", content: fullText }]);
        }
      } catch (err: any) {
        setMessages((prev) => [
          ...prev,
          { role: "system", content: `Error: ${err.message}` },
        ]);
      } finally {
        if (streamFlushRef.current) {
          clearTimeout(streamFlushRef.current);
          streamFlushRef.current = null;
        }
        pendingTextRef.current = "";
        setStreamingText("");
        setIsStreaming(false);
      }
    },
    [exit]
  );

  // Build toast line from current tool calls
  const toastLine = useMemo(() => {
    const parts: string[] = [];
    for (const tc of toolCalls) {
      const name = shortToolName(tc.name);
      parts.push(tc.error ? `✗ ${name}` : `✓ ${name}`);
    }
    for (const ntc of npcToolCalls) {
      parts.push(`${ntc.npcName} → ${shortToolName(ntc.toolName)}`);
    }
    return parts.length > 0 ? parts.join(" · ") : null;
  }, [toolCalls, npcToolCalls]);

  return (
    <Box flexDirection="column">
      {/* Header */}
      <Box borderStyle="single" borderColor="green" paddingX={1}>
        <Text color="green" bold>
          LoreKit
        </Text>
        <Box flexGrow={1} />
        <Text dimColor>
          {model}
          {sessionId ? ` · ${sessionId.slice(0, 8)}` : ""}
        </Text>
      </Box>

      {/* Chat area */}
      <Box flexDirection="column" flexGrow={1} paddingX={1}>
        <Chat
          messages={messages}
          streamingText={streamingText}
          isStreaming={isStreaming}
        />
      </Box>

      {/* Tool toast */}
      {toastLine && (
        <Box paddingX={1}>
          <Text dimColor>{toastLine}</Text>
        </Box>
      )}

      {/* Input */}
      <Box marginTop={1} flexDirection="column">
        <Input
          onSubmit={handleSubmit}
          disabled={isStreaming}
        />
      </Box>

      {/* Footer */}
      <Box paddingX={1}>
        <Text dimColor>/quit to exit · /clearlog to clear log</Text>
      </Box>
    </Box>
  );
}
