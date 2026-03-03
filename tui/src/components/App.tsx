import React, { useState, useCallback, useRef, useEffect } from "react";
import { Box, Text, useApp } from "ink";
import { Chat, type ChatMessage } from "./Chat.js";
import { Input } from "./Input.js";
import type { AgentProcess, Provider, ProviderOptions } from "../provider.js";

interface AppProps {
  provider: Provider;
  providerOpts: ProviderOptions;
  model: string;
  sessionId?: string;
}

export function App({
  provider,
  providerOpts,
  model,
  sessionId,
}: AppProps) {
  const { exit } = useApp();
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "system", content: "Starting GM process..." },
  ]);
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const agentRef = useRef<AgentProcess | null>(null);

  // Spawn the persistent GM process on mount
  useEffect(() => {
    const onError = (msg: string) => {
      setMessages((prev) => [...prev, { role: "system", content: `Error: ${msg}` }]);
    };

    const agent = provider.spawn({ ...providerOpts, onError });
    agentRef.current = agent;

    // Mark ready once the process is confirmed alive
    const timer = setTimeout(() => {
      setMessages((prev) => {
        // Only add "ready" if there are no error messages yet
        if (prev.some((m) => m.content.startsWith("Error:"))) return prev;
        return [...prev, { role: "system", content: "GM ready. Type your action." }];
      });
    }, 2000);

    return () => {
      clearTimeout(timer);
      agent.stop();
    };
  }, []);

  const handleSubmit = useCallback(async (text: string) => {
    if (!agentRef.current || isStreaming) return;

    // Handle quit
    if (text.toLowerCase() === "/quit") {
      agentRef.current.stop();
      exit();
      return;
    }

    // Check if the process is still alive
    if (!agentRef.current.alive) {
      setMessages((prev) => [
        ...prev,
        { role: "player", content: text },
        { role: "system", content: "GM process is not running. Restart with /quit and relaunch." },
      ]);
      return;
    }

    // Add player message
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

      // Finalize: move streaming text to messages
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
    }
  }, [isStreaming, exit]);

  return (
    <Box flexDirection="column" width="100%" height="100%">
      <Box borderStyle="single" borderColor="green" paddingX={1}>
        <Text color="green" bold>
          LoreKit
        </Text>
        <Text dimColor>
          {"  "}model: {model}
          {sessionId ? `  session: ${sessionId.slice(0, 8)}...` : ""}
        </Text>
      </Box>

      <Box flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        <Chat
          messages={messages}
          streamingText={streamingText}
          isStreaming={isStreaming}
        />
      </Box>

      <Input onSubmit={handleSubmit} disabled={isStreaming} />

      <Box paddingX={1}>
        <Text dimColor>Type /quit to exit</Text>
      </Box>
    </Box>
  );
}
