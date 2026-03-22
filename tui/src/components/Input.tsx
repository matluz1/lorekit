import React, { useRef, useState, useCallback } from "react";
import { Box, Text, useInput } from "ink";
import chalk from "chalk";

const DISPLAY_THROTTLE_MS = 50;
const MAX_INPUT_LENGTH = 10000;

interface InputProps {
  onSubmit: (text: string) => void;
  disabled?: boolean;
}

/** Single display state object — one setState per flush instead of two. */
interface DisplayState {
  text: string;
  cursor: number;
}

const EMPTY_DISPLAY: DisplayState = { text: "", cursor: 0 };

/**
 * Custom input component using ref-based buffer + Ink's useInput (which
 * wraps updates in reconciler.batchedUpdates).  The buffer and cursor
 * live in refs so the useInput callback always sees the latest values,
 * regardless of how far behind React renders are.  Display state is
 * flushed on a throttled schedule so Ink never re-renders faster than
 * ~20 fps for typing alone.
 */
export const Input = React.memo(function Input({
  onSubmit,
  disabled,
}: InputProps) {
  // ── Ref-based buffer (never stale in callbacks) ───────────
  const bufRef = useRef("");
  const cursorRef = useRef(0);

  // ── Display state (throttled, single object) ──────────────
  const [display, setDisplay] = useState<DisplayState>(EMPTY_DISPLAY);
  const flushRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleFlush = useCallback(() => {
    if (flushRef.current) return;
    flushRef.current = setTimeout(() => {
      flushRef.current = null;
      setDisplay({ text: bufRef.current, cursor: cursorRef.current });
    }, DISPLAY_THROTTLE_MS);
  }, []);

  const flushNow = useCallback(() => {
    if (flushRef.current) {
      clearTimeout(flushRef.current);
      flushRef.current = null;
    }
    setDisplay({ text: bufRef.current, cursor: cursorRef.current });
  }, []);

  // ── Keystroke handler (runs inside batchedUpdates) ────────
  useInput(
    (input, key) => {
      if (
        key.upArrow ||
        key.downArrow ||
        (key.ctrl && input === "c") ||
        key.tab ||
        (key.shift && key.tab)
      ) {
        return;
      }

      if (key.return) {
        const trimmed = bufRef.current.trim();
        if (!trimmed) return;
        bufRef.current = "";
        cursorRef.current = 0;
        flushNow();
        onSubmit(trimmed);
        return;
      }

      const buf = bufRef.current;
      const cur = cursorRef.current;

      if (key.leftArrow) {
        cursorRef.current = Math.max(0, cur - 1);
      } else if (key.rightArrow) {
        cursorRef.current = Math.min(buf.length, cur + 1);
      } else if (key.backspace || key.delete) {
        if (cur > 0) {
          bufRef.current = buf.slice(0, cur - 1) + buf.slice(cur);
          cursorRef.current = cur - 1;
        }
      } else if (key.ctrl && input === "u") {
        bufRef.current = buf.slice(cur);
        cursorRef.current = 0;
      } else if (key.ctrl && input === "k") {
        bufRef.current = buf.slice(0, cur);
      } else if (key.ctrl && input === "a") {
        cursorRef.current = 0;
      } else if (key.ctrl && input === "e") {
        cursorRef.current = bufRef.current.length;
      } else if (key.ctrl && input === "w") {
        const before = buf.slice(0, cur);
        const trimmed = before.replace(/\s+$/, "");
        const wordStart = trimmed.lastIndexOf(" ") + 1;
        bufRef.current = buf.slice(0, wordStart) + buf.slice(cur);
        cursorRef.current = wordStart;
      } else if (input) {
        // Truncate paste to prevent UI freeze
        const allowed = MAX_INPUT_LENGTH - buf.length;
        if (allowed <= 0) return;
        const clamped = input.length > allowed ? input.slice(0, allowed) : input;
        bufRef.current = buf.slice(0, cur) + clamped + buf.slice(cur);
        cursorRef.current = cur + clamped.length;
      }

      scheduleFlush();
    },
    { isActive: !disabled }
  );

  if (disabled) {
    return (
      <Box borderStyle="single" borderColor="gray" paddingX={1}>
        <Text dimColor>Waiting for GM...</Text>
      </Box>
    );
  }

  // ── Render with fake cursor (array join, not string concat) ──
  const { text, cursor } = display;
  let rendered: string;
  if (text.length === 0) {
    rendered = chalk.inverse(" ");
  } else {
    const parts: string[] = new Array(text.length + 1);
    let pi = 0;
    for (let i = 0; i < text.length; i++) {
      parts[pi++] = i === cursor ? chalk.inverse(text[i]!) : text[i]!;
    }
    if (cursor >= text.length) {
      parts[pi++] = chalk.inverse(" ");
    }
    rendered = parts.slice(0, pi).join("");
  }

  return (
    <Box borderStyle="single" borderColor="cyan" paddingX={1}>
      <Text color="cyan" bold>
        {">"}{" "}
      </Text>
      <Text>{rendered}</Text>
    </Box>
  );
});
