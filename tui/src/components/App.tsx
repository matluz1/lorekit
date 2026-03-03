import React, { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { Box, Text, useApp, useStdout } from "ink";
import { Chat, type ChatMessage } from "./Chat.js";
import { Input } from "./Input.js";
import { Sidebar } from "./Sidebar.js";
import type { AgentProcess, Provider, ProviderOptions } from "../provider.js";
import { getSidebarData, getActiveSessions, type SidebarData } from "../db.js";

interface AppProps {
  provider: Provider;
  providerOpts: ProviderOptions;
  model: string;
  sessionId?: string;
  lkSessionId?: number;
}

function useTerminalSize() {
  const { stdout } = useStdout();
  const [size, setSize] = useState({
    rows: stdout.rows ?? 24,
    columns: stdout.columns ?? 80,
  });

  useEffect(() => {
    const handler = () =>
      setSize({ rows: stdout.rows ?? 24, columns: stdout.columns ?? 80 });
    stdout.on("resize", handler);
    return () => {
      stdout.off("resize", handler);
    };
  }, [stdout]);

  return size;
}

// Header: 3 rows (border top + content + border bottom)
// Input:  3 rows (border top + content + border bottom)
// Footer: 1 row
const CHROME_ROWS = 7;
const SIDEBAR_WIDTH = 36;

export function App({
  provider,
  providerOpts,
  model,
  sessionId,
  lkSessionId,
}: AppProps) {
  const { exit } = useApp();
  const { rows, columns } = useTerminalSize();
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "system", content: "Starting GM process…" },
  ]);
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [detectedSessionId, setDetectedSessionId] = useState(lkSessionId);
  const agentRef = useRef<AgentProcess | null>(null);

  // Sidebar data — re-read from DB each time refreshTick changes.
  // If no session was provided, auto-detect after the GM creates one.
  const sidebarData = useMemo<SidebarData | null>(() => {
    let sid = detectedSessionId;
    if (!sid) {
      const sessions = getActiveSessions();
      if (sessions.length > 0) {
        sid = sessions[0]!.id;
        // Can't setState inside useMemo, defer it
        queueMicrotask(() => setDetectedSessionId(sid));
      }
    }
    if (!sid) return null;
    return getSidebarData(sid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detectedSessionId, refreshTick]);

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

  const handleSubmit = useCallback(
    async (text: string) => {
      if (!agentRef.current || isStreaming) return;

      if (text.toLowerCase() === "/quit") {
        agentRef.current.stop();
        exit();
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

      let fullText = "";

      try {
        for await (const chunk of agentRef.current.send(text)) {
          if (chunk.type === "text") {
            fullText += chunk.content;
            setStreamingText(fullText);
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
        setStreamingText("");
        setIsStreaming(false);
        // Refresh sidebar after each turn
        setRefreshTick((t) => t + 1);
      }
    },
    [isStreaming, exit]
  );

  const contentHeight = Math.max(4, rows - 1 - CHROME_ROWS);
  const hasSidebar = sidebarData != null;
  const chatWidth = hasSidebar
    ? Math.max(20, columns - SIDEBAR_WIDTH - 3) // -3 for sidebar border + padding
    : columns - 2; // -2 for chat padding

  return (
    <Box flexDirection="column" width={columns} height={rows - 1}>
      {/* Header */}
      <Box borderStyle="single" borderColor="green" paddingX={1}>
        <Text color="green" bold>
          LoreKit
        </Text>
        <Box flexGrow={1} />
        <Text dimColor>
          {model}
          {sessionId ? ` · ${sessionId.slice(0, 8)}` : ""}
          {detectedSessionId ? ` · session #${detectedSessionId}` : ""}
        </Text>
      </Box>

      {/* Main content: chat + sidebar */}
      <Box flexDirection="row" flexGrow={1} height={contentHeight}>
        {/* Chat area */}
        <Box
          flexDirection="column"
          flexGrow={1}
          paddingX={1}
        >
          <Chat
            messages={messages}
            streamingText={streamingText}
            isStreaming={isStreaming}
            height={contentHeight}
            width={chatWidth}
          />
        </Box>

        {/* Sidebar */}
        {hasSidebar && (
          <Box width={SIDEBAR_WIDTH}>
            <Sidebar data={sidebarData} height={contentHeight} />
          </Box>
        )}
      </Box>

      {/* Input */}
      <Input onSubmit={handleSubmit} disabled={isStreaming} />

      {/* Footer */}
      <Box paddingX={1}>
        <Text dimColor>/quit to exit</Text>
      </Box>
    </Box>
  );
}
