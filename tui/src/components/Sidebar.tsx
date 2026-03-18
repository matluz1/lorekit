import React from "react";
import { Box, Text } from "ink";
import Spinner from "ink-spinner";
import type { SidebarData } from "../db.js";
import type { ToolCallEntry, NpcToolCallEntry } from "./App.js";

interface SidebarProps {
  data: SidebarData | null;
  toolCalls: ToolCallEntry[];
  npcToolCalls: NpcToolCallEntry[];
  isStreaming: boolean;
}

/** Strip the "mcp__lorekit__" prefix for display. */
function shortToolName(name: string): string {
  return name.replace(/^mcp__lorekit__/, "");
}

export function Sidebar({ data, toolCalls, npcToolCalls, isStreaming }: SidebarProps) {
  if (!data) {
    return (
      <Box
        flexDirection="column"
        borderStyle="single"
        borderColor="gray"
      >
        <Text dimColor italic>
          No session data
        </Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <CompactPC data={data} />
      <ToolActivity toolCalls={toolCalls} isStreaming={isStreaming} />
      <NPCToolsPanel npcToolCalls={npcToolCalls} />
      <RegionPanel data={data} />
      <TimelinePanel data={data} />
    </Box>
  );
}

// ── Compact PC ────────────────────────────────────────

function CompactPC({
  data,
}: {
  data: SidebarData;
}) {
  const { pc, attrs } = data;

  // Find HP from attributes
  const hp = attrs.find(
    (a) => a.key === "hit_points" || a.key === "hp"
  );

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="yellow"
      paddingX={1}
    >
      <Text color="yellow" bold>
        {pc.name}
      </Text>
      <Text dimColor>
        Lvl {pc.level}
        {hp ? ` · HP ${hp.value}` : ""}
      </Text>
    </Box>
  );
}

// ── Tool Activity ─────────────────────────────────────

function ToolActivity({
  toolCalls,
  isStreaming,
}: {
  toolCalls: ToolCallEntry[];
  isStreaming: boolean;
}) {
  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="cyan"
      paddingX={1}
    >
      <Text color="cyan" bold>
        GM Tools
      </Text>
      {toolCalls.length === 0 && !isStreaming ? (
        <Text dimColor italic>
          Waiting for turn
        </Text>
      ) : toolCalls.length === 0 && isStreaming ? (
        <Text dimColor italic>
          <Spinner type="dots" />{" "}Thinking…
        </Text>
      ) : (
        toolCalls.map((tc, i) => {
          const name = shortToolName(tc.name);
          const isLast = i === toolCalls.length - 1 && isStreaming;
          const isFailed = tc.error === true;
          return (
            <Box key={`${tc.ts}-${i}`}>
              <Text
                color={isFailed ? "red" : "cyan"}
              >
                {isFailed ? (
                  <Text color="red">x </Text>
                ) : isLast ? (
                  <><Spinner type="dots" />{" "}</>
                ) : (
                  <Text color="green">+ </Text>
                )}
                {name}
                {isFailed && <Text color="red" dimColor> FAILED</Text>}
              </Text>
            </Box>
          );
        })
      )}
    </Box>
  );
}

// ── NPC Tools Panel ───────────────────────────────────

function NPCToolsPanel({
  npcToolCalls,
}: {
  npcToolCalls: NpcToolCallEntry[];
}) {
  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="red"
      paddingX={1}
    >
      <Text color="red" bold>
        NPC Tools
      </Text>
      {npcToolCalls.length === 0 ? (
        <Text dimColor italic>
          No NPC interactions
        </Text>
      ) : (
        npcToolCalls.map((entry, i) => {
          const name = shortToolName(entry.toolName);
          return (
            <Box key={`${entry.ts}-${i}`}>
              <Text color="redBright">
                <Text color="green">+ </Text>
                <Text bold>{entry.npcName}</Text>
                <Text dimColor>{" → "}</Text>
                {name}
              </Text>
            </Box>
          );
        })
      )}
    </Box>
  );
}

// ── Region Panel ───────────────────────────────────────

function RegionPanel({
  data,
}: {
  data: SidebarData;
}) {
  const { region, regionNPCs } = data;

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="blue"
      paddingX={1}
    >
      <Text color="blue" bold>
        {region ? region.name : "No region"}
      </Text>
      {region?.description && (
        <Text dimColor wrap="truncate-end">
          {region.description}
        </Text>
      )}
      {regionNPCs.length > 0 && (
        <Box flexDirection="column">
          {regionNPCs.map((npc) => (
            <Text key={npc.id} wrap="truncate-end">
              {npc.name}
              <Text dimColor> Lvl {npc.level}</Text>
            </Text>
          ))}
        </Box>
      )}
    </Box>
  );
}

// ── Timeline Panel ─────────────────────────────────────

function TimelinePanel({
  data,
}: {
  data: SidebarData;
}) {
  const { timeline } = data;

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="magenta"
      paddingX={1}
    >
      <Text color="magenta" bold>
        Timeline
      </Text>
      {timeline.length === 0 ? (
        <Text dimColor italic>
          No entries yet
        </Text>
      ) : (
        // timeline is DESC from DB, reverse so oldest is first
        [...timeline].reverse().map((entry) => (
          <Box key={entry.id} flexDirection="column">
            <Text wrap="truncate-end">
              <Text color="magenta" dimColor>
                [{entry.entry_type}]{" "}
              </Text>
              <Text>{entry.summary || truncate(entry.content, 60)}</Text>
            </Text>
          </Box>
        ))
      )}
    </Box>
  );
}

function truncate(text: string, max: number): string {
  const first = text.split("\n")[0] ?? text;
  if (first.length <= max) return first;
  return first.slice(0, max - 1) + "…";
}
