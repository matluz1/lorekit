// examples/tui/src/components/App.tsx
import React, { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { Box, Text, useApp } from "ink";
import { Chat, chatMsg, type ChatMessage } from "./Chat.js";
import { Input } from "./Input.js";
import { sendMessage, save, saveList, unsavedCount, loadSave, listenEvents, type GameEvent } from "../api.js";

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

/** Strip the "mcp__lorekit__" prefix for display. */
function shortToolName(name: string): string {
  return name.replace(/^mcp__lorekit__/, "");
}

export function App() {
  const { exit } = useApp();

  // ── State ──────────────────────────────────────────
  const [messages, setMessages] = useState<ChatMessage[]>([
    chatMsg("system", "Connecting to server…"),
  ]);
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const isStreamingRef = useRef(false);

  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  // ── Save/load state ─────────────────────────────────
  const pendingLoadRef = useRef<string | null>(null);

  // ── Tool call tracking ────────────────────────────────
  const [toolCalls, setToolCalls] = useState<ToolCallEntry[]>([]);
  const [npcToolCalls, setNpcToolCalls] = useState<NpcToolCallEntry[]>([]);

  // Listen to server lifecycle events
  useEffect(() => {
    let cancelled = false;
    async function listen() {
      for await (const event of listenEvents()) {
        if (cancelled) break;
        if (event.type === "system") {
          setMessages((prev) => [...prev, chatMsg("system", event.content)]);
        }
      }
    }
    listen();
    return () => { cancelled = true; };
  }, []);

  // Throttle streaming text updates
  const streamFlushRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingTextRef = useRef("");

  const flushStreamingText = useCallback(() => {
    setStreamingText(pendingTextRef.current);
    streamFlushRef.current = null;
  }, []);

  // ── Submit handler ───────────────────────────────────
  const handleSubmit = useCallback(
    async (text: string) => {
      if (isStreamingRef.current) return;

      if (text.toLowerCase() === "/quit") {
        exit();
        return;
      }

      // Save/load slash commands
      if (text.toLowerCase() === "/saves") {
        try {
          const result = await saveList();
          setMessages((prev) => [...prev, chatMsg("system", result)]);
        } catch (err: any) {
          setMessages((prev) => [...prev, chatMsg("system", `Save list failed: ${err.message}`)]);
        }
        return;
      }
      if (text.toLowerCase().startsWith("/save")) {
        const name = text.slice(5).trim() || undefined;
        try {
          const result = await save(name);
          setMessages((prev) => [...prev, chatMsg("system", `Game saved as '${result}'.`)]);
        } catch (err: any) {
          setMessages((prev) => [...prev, chatMsg("system", `Save failed: ${err.message}`)]);
        }
        return;
      }
      if (text.toLowerCase().startsWith("/load")) {
        const name = text.slice(5).trim();
        if (!name) {
          setMessages((prev) => [...prev, chatMsg("system", "Usage: /load <save name>")]);
          return;
        }
        try {
          const count = await unsavedCount();
          if (count > 0) {
            setMessages((prev) => [
              ...prev,
              chatMsg("system", `Warning: Loading will discard ${count} unsaved turn(s). Type /confirm to proceed or anything else to cancel.`),
            ]);
            pendingLoadRef.current = name;
            return;
          }
          const result = await loadSave(name);
          setMessages((prev) => [...prev, chatMsg("system", result)]);
        } catch (err: any) {
          setMessages((prev) => [...prev, chatMsg("system", `Load failed: ${err.message}`)]);
        }
        return;
      }
      if (text.toLowerCase() === "/confirm" && pendingLoadRef.current) {
        const name = pendingLoadRef.current;
        pendingLoadRef.current = null;
        try {
          const result = await loadSave(name);
          setMessages((prev) => [...prev, chatMsg("system", result)]);
        } catch (err: any) {
          setMessages((prev) => [...prev, chatMsg("system", `Load failed: ${err.message}`)]);
        }
        return;
      }
      if (pendingLoadRef.current) {
        pendingLoadRef.current = null;
        setMessages((prev) => [...prev, chatMsg("system", "Load cancelled.")]);
      }

      // ── Send player message via HTTP ───────────────
      setMessages((prev) => [...prev, chatMsg("player", text)]);
      setIsStreaming(true);
      setStreamingText("");
      pendingTextRef.current = "";
      setToolCalls([]);
      setNpcToolCalls([]);

      const textParts: string[] = [];

      try {
        for await (const event of sendMessage(text)) {
          if (event.type === "narration_delta") {
            textParts.push(event.content);
            pendingTextRef.current = textParts.join("");
            if (!streamFlushRef.current) {
              streamFlushRef.current = setTimeout(flushStreamingText, 80);
            }
          } else if (event.type === "tool_activity") {
            setToolCalls((prev) => [
              ...prev,
              { name: event.content, ts: Date.now() },
            ]);
          } else if (event.type === "npc_activity") {
            const [npcName, toolsCsv] = event.content.split(":");
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
          } else if (event.type === "narration") {
            // Final accumulated text — use this as the definitive message
            setMessages((prev) => [...prev, chatMsg("gm", event.content)]);
          } else if (event.type === "error") {
            setMessages((prev) => [
              ...prev,
              chatMsg("system", `Error: ${event.content}`),
            ]);
          } else if (event.type === "system") {
            setMessages((prev) => [
              ...prev,
              chatMsg("system", event.content),
            ]);
          }
        }

        // If no narration event came, use accumulated deltas
        if (textParts.length > 0) {
          const fullText = textParts.join("");
          // Check if we already added this as a narration event
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === "gm" && last.content === fullText) return prev;
            if (fullText) return [...prev, chatMsg("gm", fullText)];
            return prev;
          });
        }
      } catch (err: any) {
        setMessages((prev) => [
          ...prev,
          chatMsg("system", `Error: ${err.message}`),
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
    [exit, flushStreamingText],
  );

  // Build toast line from current tool calls
  const toastLine = useMemo(() => {
    const parts: string[] = [];
    for (const tc of toolCalls) {
      parts.push(`✓ ${shortToolName(tc.name)}`);
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
        <Text dimColor>lorekit</Text>
      </Box>

      {/* Chat area */}
      <Box flexDirection="column" flexGrow={1} paddingX={1}>
        <Chat
          messages={messages}
          streamingText={streamingText}
          isStreaming={isStreaming}
        />
      </Box>

      {/* Input */}
      <Box marginTop={1} flexDirection="column">
        {toastLine && (
          <Box paddingX={1}>
            <Text dimColor>{toastLine}</Text>
          </Box>
        )}
        <Input
          onSubmit={handleSubmit}
          disabled={isStreaming}
        />
      </Box>

      {/* Footer */}
      <Box paddingX={1}>
        <Text dimColor>/save [name] · /load name · /saves · /quit</Text>
      </Box>
    </Box>
  );
}
