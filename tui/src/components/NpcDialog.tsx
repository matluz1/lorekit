import React, { useMemo } from "react";
import { Box, Text } from "ink";
import Spinner from "ink-spinner";

export interface NpcMessage {
  role: "npc" | "player" | "system";
  content: string;
}

interface NpcDialogProps {
  npcName: string;
  messages: NpcMessage[];
  streamingText: string;
  isStreaming: boolean;
  height: number;
  width: number;
}

function estimateLines(text: string, width: number): number {
  if (width <= 0) return 1;
  let total = 0;
  for (const line of text.split("\n")) {
    total += Math.max(1, Math.ceil((line.length + 1) / width));
  }
  return total;
}

function getVisibleMessages(
  messages: NpcMessage[],
  streamingText: string,
  isStreaming: boolean,
  height: number,
  width: number
): NpcMessage[] {
  let remaining = height - 1; // -1 for the NPC name header

  if (isStreaming) {
    const streamLines = streamingText
      ? estimateLines(streamingText, width) + 1
      : 2;
    remaining -= streamLines;
  }

  const visible: NpcMessage[] = [];
  for (let i = messages.length - 1; i >= 0 && remaining > 0; i--) {
    const msg = messages[i]!;
    const lines = estimateLines(msg.content, width) + 1;
    if (lines > remaining && visible.length > 0) break;
    visible.unshift(msg);
    remaining -= lines;
  }
  return visible;
}

export function NpcDialog({
  npcName,
  messages,
  streamingText,
  isStreaming,
  height,
  width,
}: NpcDialogProps) {
  const visible = useMemo(
    () =>
      getVisibleMessages(messages, streamingText, isStreaming, height, width),
    [messages, streamingText, isStreaming, height, width]
  );

  return (
    <Box flexDirection="column" height={height} overflow="hidden">
      <Text color="red" bold>
        Talking to {npcName}
        <Text dimColor> (Esc to leave)</Text>
      </Text>

      {visible.map((msg, i) => (
        <Box
          key={i}
          marginBottom={i < visible.length - 1 ? 1 : 0}
        >
          {msg.role === "player" ? (
            <Text>
              <Text color="cyan" bold>
                {">"}{" "}
              </Text>
              <Text>{msg.content}</Text>
            </Text>
          ) : msg.role === "system" ? (
            <Text color="yellow" dimColor italic>
              {msg.content}
            </Text>
          ) : (
            <Text color="red">{msg.content}</Text>
          )}
        </Box>
      ))}
      {isStreaming && (
        <Box>
          <Text color="red">
            {streamingText || ""}
            <Text color="yellow">
              {" "}
              <Spinner type="dots" />
            </Text>
          </Text>
        </Box>
      )}
    </Box>
  );
}
