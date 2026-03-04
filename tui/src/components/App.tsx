import React, { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { Box, Text, useApp, useStdout, useInput } from "ink";
import { Chat, type ChatMessage } from "./Chat.js";
import { NpcDialog, type NpcMessage } from "./NpcDialog.js";
import { Input } from "./Input.js";
import { Sidebar } from "./Sidebar.js";
import type { AgentProcess, Provider, ProviderOptions } from "../provider.js";
import { getSidebarData, getActiveSessions, getNPCsByName, getPC, type SidebarData } from "../db.js";
import { buildNpcContext, spawnNpc } from "../npc.js";

type View = "gm" | "npc";

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

  // ── GM state ──────────────────────────────────────────
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "system", content: "Starting GM process…" },
  ]);
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [detectedSessionId, setDetectedSessionId] = useState(lkSessionId);
  const agentRef = useRef<AgentProcess | null>(null);

  // ── NPC state ─────────────────────────────────────────
  const [view, setView] = useState<View>("gm");
  const [npcName, setNpcName] = useState("");
  const [npcMessages, setNpcMessages] = useState<NpcMessage[]>([]);
  const [npcStreamingText, setNpcStreamingText] = useState("");
  const [isNpcStreaming, setIsNpcStreaming] = useState(false);
  const npcAgentRef = useRef<AgentProcess | null>(null);

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

  // ── Escape key: leave NPC dialogue ────────────────────
  useInput((input, key) => {
    if (key.escape && view === "npc" && !isNpcStreaming) {
      leaveNpcDialog();
    }
  });

  const leaveNpcDialog = useCallback(() => {
    npcAgentRef.current?.stop();
    npcAgentRef.current = null;
    setView("gm");
    setNpcMessages([]);
    setNpcStreamingText("");
    setNpcName("");
  }, []);

  // ── Enter NPC dialogue ────────────────────────────────
  const enterNpcDialog = useCallback(
    async (name: string) => {
      const sid = detectedSessionId;
      if (!sid) {
        setMessages((prev) => [
          ...prev,
          { role: "system", content: "No active session — cannot talk to NPCs." },
        ]);
        return;
      }

      const pc = getPC(sid);
      const pcName = pc?.name ?? "the player";

      const matches = getNPCsByName(sid, name);
      if (matches.length === 0) {
        setMessages((prev) => [
          ...prev,
          { role: "system", content: `No NPC named "${name}" found in this session.` },
        ]);
        return;
      }
      if (matches.length > 1) {
        const names = matches.map((m) => m.name).join(", ");
        setMessages((prev) => [
          ...prev,
          { role: "system", content: `Multiple NPCs match "${name}": ${names}. Be more specific.` },
        ]);
        return;
      }

      const npc = matches[0]!;
      const ctx = buildNpcContext(npc.id, sid, pcName);
      if (!ctx) {
        setMessages((prev) => [
          ...prev,
          { role: "system", content: `Could not load context for ${npc.name}.` },
        ]);
        return;
      }

      setNpcName(ctx.npcName);
      setNpcMessages([
        { role: "system", content: `You approach ${ctx.npcName}.` },
      ]);
      setView("npc");

      // Spawn persistent NPC agent (lives for the whole conversation)
      const npcAgent = spawnNpc(provider, ctx, {
        mcpConfig: providerOpts.mcpConfig,
        cwd: providerOpts.cwd,
        onError: (msg: string) => {
          setNpcMessages((prev) => [
            ...prev,
            { role: "system", content: `Error: ${msg}` },
          ]);
        },
      });
      npcAgentRef.current = npcAgent;

      // Send initial context as first turn (NPC acknowledges silently)
      setIsNpcStreaming(true);
      try {
        for await (const chunk of npcAgent.send(ctx.initialContext)) {
          // Discard the NPC's response to context seeding — it's just an ack
        }
      } catch {
        // best effort
      }
      setIsNpcStreaming(false);
    },
    [detectedSessionId, provider, providerOpts]
  );

  // ── GM submit ─────────────────────────────────────────
  const handleGmSubmit = useCallback(
    async (text: string) => {
      if (!agentRef.current || isStreaming) return;

      if (text.toLowerCase() === "/quit") {
        agentRef.current.stop();
        npcAgentRef.current?.stop();
        exit();
        return;
      }

      // /talk <npc_name> — switch to NPC dialogue
      const talkMatch = text.match(/^\/talk\s+(.+)$/i);
      if (talkMatch) {
        enterNpcDialog(talkMatch[1]!);
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
    [isStreaming, exit, enterNpcDialog]
  );

  // ── NPC submit ────────────────────────────────────────
  const handleNpcSubmit = useCallback(
    async (text: string) => {
      if (isNpcStreaming) return;

      if (text.toLowerCase() === "/leave") {
        leaveNpcDialog();
        return;
      }

      if (!npcAgentRef.current?.alive) {
        setNpcMessages((prev) => [
          ...prev,
          { role: "system", content: "NPC process died. Press Esc and try again." },
        ]);
        return;
      }

      setNpcMessages((prev) => [...prev, { role: "player", content: text }]);
      setIsNpcStreaming(true);
      setNpcStreamingText("");

      let fullText = "";

      try {
        for await (const chunk of npcAgentRef.current.send(text)) {
          if (chunk.type === "text") {
            fullText += chunk.content;
            setNpcStreamingText(fullText);
          } else if (chunk.type === "error") {
            setNpcMessages((prev) => [
              ...prev,
              { role: "system", content: `Error: ${chunk.content}` },
            ]);
          }
        }

        if (fullText) {
          setNpcMessages((prev) => [
            ...prev,
            { role: "npc", content: fullText },
          ]);

          // Log dialogue to timeline via GM so it appears in the shared context.
          // Fire-and-forget: send to the persistent GM agent.
          const pc = detectedSessionId ? getPC(detectedSessionId) : undefined;
          const pcName = pc?.name ?? "the player";
          if (agentRef.current?.alive) {
            const logMsg = `[NPC dialogue log — do NOT narrate, just save to timeline]\n${npcName} said to ${pcName}: "${fullText.slice(0, 500)}"`;
            (async () => {
              try {
                for await (const _ of agentRef.current!.send(logMsg)) {
                  // discard
                }
              } catch {
                // best effort
              }
              setRefreshTick((t) => t + 1);
            })();
          }
        }
      } catch (err: any) {
        setNpcMessages((prev) => [
          ...prev,
          { role: "system", content: `Error: ${err.message}` },
        ]);
      } finally {
        setNpcStreamingText("");
        setIsNpcStreaming(false);
      }
    },
    [isNpcStreaming, detectedSessionId, npcName, leaveNpcDialog]
  );

  const contentHeight = Math.max(4, rows - 1 - CHROME_ROWS);
  const hasSidebar = sidebarData != null;
  const chatWidth = hasSidebar
    ? Math.max(20, columns - SIDEBAR_WIDTH - 3) // -3 for sidebar border + padding
    : columns - 2; // -2 for chat padding

  const currentlyStreaming = view === "gm" ? isStreaming : isNpcStreaming;

  return (
    <Box flexDirection="column" width={columns} height={rows - 1}>
      {/* Header */}
      <Box borderStyle="single" borderColor={view === "gm" ? "green" : "red"} paddingX={1}>
        <Text color={view === "gm" ? "green" : "red"} bold>
          LoreKit
          {view === "npc" && <Text color="red"> · {npcName}</Text>}
        </Text>
        <Box flexGrow={1} />
        <Text dimColor>
          {model}
          {sessionId ? ` · ${sessionId.slice(0, 8)}` : ""}
          {detectedSessionId ? ` · session #${detectedSessionId}` : ""}
        </Text>
      </Box>

      {/* Main content: chat/npc + sidebar */}
      <Box flexDirection="row" flexGrow={1} height={contentHeight}>
        {/* Chat / NPC dialogue area */}
        <Box flexDirection="column" flexGrow={1} paddingX={1}>
          {view === "gm" ? (
            <Chat
              messages={messages}
              streamingText={streamingText}
              isStreaming={isStreaming}
              height={contentHeight}
              width={chatWidth}
            />
          ) : (
            <NpcDialog
              npcName={npcName}
              messages={npcMessages}
              streamingText={npcStreamingText}
              isStreaming={isNpcStreaming}
              height={contentHeight}
              width={chatWidth}
            />
          )}
        </Box>

        {/* Sidebar */}
        {hasSidebar && (
          <Box width={SIDEBAR_WIDTH}>
            <Sidebar data={sidebarData} height={contentHeight} />
          </Box>
        )}
      </Box>

      {/* Input */}
      <Input
        onSubmit={view === "gm" ? handleGmSubmit : handleNpcSubmit}
        disabled={currentlyStreaming}
      />

      {/* Footer */}
      <Box paddingX={1}>
        <Text dimColor>
          {view === "gm"
            ? "/talk <name> to chat with NPC · /quit to exit"
            : "/leave or Esc to return to GM · /quit to exit"}
        </Text>
      </Box>
    </Box>
  );
}
