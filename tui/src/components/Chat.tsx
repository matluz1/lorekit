import React from "react";
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

export function Chat({ messages, streamingText, isStreaming }: ChatProps) {
  return (
    <Box flexDirection="column" flexGrow={1}>
      {messages.map((msg, i) => (
        <Box key={i} marginBottom={1}>
          {msg.role === "player" ? (
            <Text>
              <Text color="cyan" bold>{">"} </Text>
              <Text>{msg.content}</Text>
            </Text>
          ) : msg.role === "system" ? (
            <Text color="yellow" dimColor italic>
              {msg.content}
            </Text>
          ) : (
            <Text color="green">{msg.content}</Text>
          )}
        </Box>
      ))}
      {isStreaming && (
        <Box>
          <Text color="green">
            {streamingText}
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
