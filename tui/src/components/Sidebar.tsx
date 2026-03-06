import React from "react";
import { Box, Text } from "ink";
import Spinner from "ink-spinner";
import type { SidebarData } from "../db.js";
import type { ToolCallEntry } from "./App.js";

interface SidebarProps {
  data: SidebarData | null;
  height: number;
  toolCalls: ToolCallEntry[];
  isStreaming: boolean;
}

/** Strip the "mcp__lorekit__" prefix for display. */
function shortToolName(name: string): string {
  return name.replace(/^mcp__lorekit__/, "");
}

export function Sidebar({ data, height, toolCalls, isStreaming }: SidebarProps) {
  if (!data) {
    return (
      <Box
        flexDirection="column"
        borderStyle="single"
        borderColor="gray"
        height={height}
        overflow="hidden"
      >
        <Text dimColor italic>
          No session data
        </Text>
      </Box>
    );
  }

  // Divide height: PC compact ~4, tool activity ~30%, region ~20%, timeline rest
  const pcH = 4;
  const toolH = Math.max(4, Math.floor(height * 0.3));
  const regionH = Math.max(3, Math.floor(height * 0.2));
  const timelineH = Math.max(3, height - pcH - toolH - regionH);

  return (
    <Box flexDirection="column" height={height} overflow="hidden">
      <CompactPC data={data} height={pcH} />
      <ToolActivity toolCalls={toolCalls} isStreaming={isStreaming} height={toolH} />
      <RegionPanel data={data} height={regionH} />
      <TimelinePanel data={data} height={timelineH} />
    </Box>
  );
}

// ── Compact PC ────────────────────────────────────────

function CompactPC({
  data,
  height,
}: {
  data: SidebarData;
  height: number;
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
      height={height}
      overflow="hidden"
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
  height,
}: {
  toolCalls: ToolCallEntry[];
  isStreaming: boolean;
  height: number;
}) {
  // Show most recent calls that fit, newest last
  const maxEntries = Math.max(1, height - 3); // -3 for border + header
  const visible = toolCalls.slice(-maxEntries);

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="cyan"
      paddingX={1}
      height={height}
      overflow="hidden"
    >
      <Text color="cyan" bold>
        GM Tools
      </Text>
      {visible.length === 0 && !isStreaming ? (
        <Text dimColor italic>
          Waiting for turn
        </Text>
      ) : visible.length === 0 && isStreaming ? (
        <Text dimColor italic>
          <Spinner type="dots" />{" "}Thinking…
        </Text>
      ) : (
        visible.map((tc, i) => {
          const name = shortToolName(tc.name);
          const isNpcInteract = name === "npc_interact";
          const isLast = i === visible.length - 1 && isStreaming;
          const isFailed = tc.error === true;
          return (
            <Box key={`${tc.ts}-${i}`}>
              <Text
                color={isFailed ? "red" : isNpcInteract ? "red" : "cyan"}
                bold={isNpcInteract}
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

// ── Region Panel ───────────────────────────────────────

function RegionPanel({
  data,
  height,
}: {
  data: SidebarData;
  height: number;
}) {
  const { region, regionNPCs } = data;

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="blue"
      paddingX={1}
      height={height}
      overflow="hidden"
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
  height,
}: {
  data: SidebarData;
  height: number;
}) {
  const { timeline } = data;

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="magenta"
      paddingX={1}
      height={height}
      overflow="hidden"
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
