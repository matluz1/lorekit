import React, { useState, useEffect, useMemo, type ReactNode } from "react";
import { Box, Text } from "ink";

// ── Module-level regex (compiled once) ──────────────────────
const MARKDOWN_RE = /(\*{1,3})((?:(?!\1).)+?)\1/g;

let nextMsgId = 1;

export interface ChatMessage {
  id: number;
  role: "gm" | "player" | "system";
  content: string;
}

/** Create a ChatMessage with an auto-incrementing stable ID. */
export function chatMsg(role: ChatMessage["role"], content: string): ChatMessage {
  return { id: nextMsgId++, role, content };
}

interface ChatProps {
  messages: ChatMessage[];
  streamingText: string;
  isStreaming: boolean;
}

const MAX_VISIBLE_MESSAGES = 80;

/**
 * Parse inline markdown (bold, italic, bold-italic) into Ink <Text> nodes.
 */
function parseInline(text: string, baseColor?: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;

  for (const m of text.matchAll(MARKDOWN_RE)) {
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

/** Memoized single message row — only re-renders when content changes. */
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

/** Separate component for streaming text — isolates re-renders from message list. */
const StreamingBlock = React.memo(function StreamingBlock({
  text,
}: {
  text: string;
}) {
  return (
    <Box>
      <Text>
        {parseInline(text || "", "green")}
        <Text>{" "}</Text>
        <SlowSpinner />
      </Text>
    </Box>
  );
});

export const Chat = React.memo(function Chat({
  messages,
  streamingText,
  isStreaming,
}: ChatProps) {
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
          key={msg.id}
          msg={msg}
          isLast={i === visible.length - 1 && !isStreaming}
        />
      ))}
      {isStreaming && <StreamingBlock text={streamingText} />}
    </Box>
  );
});
