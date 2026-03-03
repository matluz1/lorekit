import React from "react";
import { Box, Text } from "ink";
import type { SidebarData } from "../db.js";

interface SidebarProps {
  data: SidebarData | null;
  height: number;
}

export function Sidebar({ data, height }: SidebarProps) {
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

  // Divide height among 3 panels: char ~50%, region ~20%, timeline ~30%
  const charH = Math.max(5, Math.floor(height * 0.5));
  const regionH = Math.max(3, Math.floor(height * 0.2));
  const timelineH = Math.max(3, height - charH - regionH);

  return (
    <Box flexDirection="column" height={height} overflow="hidden">
      <CharSheet data={data} height={charH} />
      <RegionPanel data={data} height={regionH} />
      <TimelinePanel data={data} height={timelineH} />
    </Box>
  );
}

// ── Character Sheet ────────────────────────────────────

function CharSheet({
  data,
  height,
}: {
  data: SidebarData;
  height: number;
}) {
  const { pc, attrs, inventory, abilities } = data;

  // Group attributes by category
  const grouped: Record<string, { key: string; value: string }[]> = {};
  for (const a of attrs) {
    (grouped[a.category] ??= []).push({ key: a.key, value: a.value });
  }

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
        Lvl {pc.level} · {pc.status}
      </Text>

      {/* Identity / stats attributes */}
      {Object.entries(grouped).map(([cat, items]) => (
        <Box key={cat} flexDirection="column">
          {items.map((item) => (
            <Text key={item.key} wrap="truncate-end">
              <Text dimColor>{item.key}: </Text>
              {item.value}
            </Text>
          ))}
        </Box>
      ))}

      {/* Inventory */}
      {inventory.length > 0 && (
        <Box flexDirection="column">
          <Text color="yellow" dimColor>
            Inventory
          </Text>
          {inventory.map((item) => (
            <Text key={item.id} wrap="truncate-end">
              {item.equipped ? "[E] " : "    "}
              {item.name}
              {item.quantity > 1 ? ` x${item.quantity}` : ""}
            </Text>
          ))}
        </Box>
      )}

      {/* Abilities */}
      {abilities.length > 0 && (
        <Box flexDirection="column">
          <Text color="yellow" dimColor>
            Abilities
          </Text>
          {abilities.map((ab) => (
            <Text key={ab.name} wrap="truncate-end">
              {ab.name}
              <Text dimColor>
                {" "}
                ({ab.uses})
              </Text>
            </Text>
          ))}
        </Box>
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
          <Text color="blue" dimColor>
            NPCs
          </Text>
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
