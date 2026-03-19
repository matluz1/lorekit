import React, { type ReactNode } from "react";
import { Box, Text } from "ink";
import Spinner from "ink-spinner";

export interface ChatMessage {
  role: "gm" | "player" | "system";
  content: string;
}

interface ChatProps {
  messages: ChatMessage[];
  streamingText: string;
  isStreaming: boolean;
}

/**
 * Parse inline markdown (bold, italic, bold-italic) into Ink <Text> nodes.
 * Handles ***bold italic***, **bold**, and *italic*.
 */
function parseInline(text: string, baseColor?: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  // Match ***…***, **…**, or *…* (non-greedy, no nesting)
  const re = /(\*{1,3})((?:(?!\1).)+?)\1/g;
  let last = 0;

  for (const m of text.matchAll(re)) {
    const idx = m.index!;
    if (idx > last) {
      nodes.push(<Text key={last} color={baseColor}>{text.slice(last, idx)}</Text>);
    }
    const stars = m[1]!.length;
    const inner = m[2]!;
    const bold = stars >= 2;
    const italic = stars === 1 || stars === 3;
    nodes.push(
      <Text key={idx} color={baseColor} bold={bold} italic={italic}>
        {inner}
      </Text>
    );
    last = idx + m[0]!.length;
  }

  if (last < text.length) {
    nodes.push(<Text key={last} color={baseColor}>{text.slice(last)}</Text>);
  }

  return nodes.length > 0 ? nodes : [<Text key={0} color={baseColor}>{text}</Text>];
}

export function Chat({
  messages,
  streamingText,
  isStreaming,
}: ChatProps) {
  return (
    <Box flexDirection="column">
      {messages.map((msg, i) => (
        <Box key={i} marginBottom={i < messages.length - 1 ? 1 : 0}>
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
            <Text>{parseInline(msg.content, "green")}</Text>
          )}
        </Box>
      ))}
      {isStreaming && (
        <Box>
          <Text>
            {parseInline(streamingText || "", "green")}
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
