import React, { useState, useEffect, useMemo, type ReactNode } from "react";
import { Box, Text } from "ink";

export interface ChatMessage {
  role: "gm" | "player" | "system";
  content: string;
}

interface ChatProps {
  messages: ChatMessage[];
  streamingText: string;
  isStreaming: boolean;
}

const MAX_VISIBLE_MESSAGES = 80;

/**
 * Parse inline markdown (bold, italic, bold-italic) into Ink <Text> nodes.
 * Handles ***bold italic***, **bold**, and *italic*.
 */
function parseInline(text: string, baseColor?: string): ReactNode[] {
  const nodes: ReactNode[] = [];
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

/** Memoized single message row. */
const MessageRow = React.memo(function MessageRow({
  msg,
  isLast,
}: {
  msg: ChatMessage;
  isLast: boolean;
}) {
  return (
    <Box marginBottom={isLast ? 0 : 1}>
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
  );
});

/** Slow spinner — 2 frames at 960ms. */
const SPINNER_FRAMES = ["⠂", "⠐"];
function SlowSpinner() {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setFrame((f) => (f + 1) % SPINNER_FRAMES.length), 960);
    return () => clearInterval(id);
  }, []);
  return <Text color="yellow">{SPINNER_FRAMES[frame]}</Text>;
}

export const Chat = React.memo(function Chat({
  messages,
  streamingText,
  isStreaming,
}: ChatProps) {
  // Only render the last N messages to keep layout cost bounded
  const visible = useMemo(
    () => messages.slice(-MAX_VISIBLE_MESSAGES),
    [messages]
  );

  const truncated = messages.length > MAX_VISIBLE_MESSAGES;

  return (
    <Box flexDirection="column">
      {truncated && (
        <Box marginBottom={1}>
          <Text dimColor italic>
            ({messages.length - MAX_VISIBLE_MESSAGES} earlier messages hidden)
          </Text>
        </Box>
      )}
      {visible.map((msg, i) => (
        <MessageRow
          key={messages.length - visible.length + i}
          msg={msg}
          isLast={i === visible.length - 1 && !isStreaming}
        />
      ))}
      {isStreaming && (
        <Box>
          <Text>
            {parseInline(streamingText || "", "green")}
            <Text>{" "}</Text>
            <SlowSpinner />
          </Text>
        </Box>
      )}
    </Box>
  );
});
