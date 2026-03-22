import React, { useRef, useState, useCallback } from "react";
import { Box, Text, useInput } from "ink";
import chalk from "chalk";

const DISPLAY_THROTTLE_MS = 16;

interface InputProps {
  onSubmit: (text: string) => void;
  disabled?: boolean;
}

/**
 * Custom input component using ref-based buffer + Ink's useInput (which
 * wraps updates in reconciler.batchedUpdates).  The buffer and cursor
 * live in refs so the useInput callback always sees the latest values,
 * regardless of how far behind React renders are.  Display state is
 * flushed to a useState on a throttled schedule so Ink never re-renders
 * faster than ~60 fps for typing alone.
 */
export const Input = React.memo(function Input({
  onSubmit,
  disabled,
}: InputProps) {
  // ── Ref-based buffer (never stale in callbacks) ───────────
  const bufRef = useRef("");
  const cursorRef = useRef(0);

  // ── Display state (throttled) ─────────────────────────────
  const [display, setDisplay] = useState("");
  const [displayCursor, setDisplayCursor] = useState(0);
  const flushRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleFlush = useCallback(() => {
    if (flushRef.current) return;
    flushRef.current = setTimeout(() => {
      flushRef.current = null;
      setDisplay(bufRef.current);
      setDisplayCursor(cursorRef.current);
    }, DISPLAY_THROTTLE_MS);
  }, []);

  const flushNow = useCallback(() => {
    if (flushRef.current) {
      clearTimeout(flushRef.current);
      flushRef.current = null;
    }
    setDisplay(bufRef.current);
    setDisplayCursor(cursorRef.current);
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
        // Ctrl+U: clear line before cursor
        bufRef.current = buf.slice(cur);
        cursorRef.current = 0;
      } else if (key.ctrl && input === "k") {
        // Ctrl+K: clear line after cursor
        bufRef.current = buf.slice(0, cur);
      } else if (key.ctrl && input === "a") {
        // Ctrl+A: home
        cursorRef.current = 0;
      } else if (key.ctrl && input === "e") {
        // Ctrl+E: end
        cursorRef.current = bufRef.current.length;
      } else if (key.ctrl && input === "w") {
        // Ctrl+W: delete word back
        const before = buf.slice(0, cur);
        const trimmed = before.replace(/\s+$/, "");
        const wordStart = trimmed.lastIndexOf(" ") + 1;
        bufRef.current = buf.slice(0, wordStart) + buf.slice(cur);
        cursorRef.current = wordStart;
      } else if (input) {
        // Normal character(s) — handles paste (multi-char input) too
        bufRef.current = buf.slice(0, cur) + input + buf.slice(cur);
        cursorRef.current = cur + input.length;
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

  // ── Render with fake cursor ─────────────────────────────
  let rendered = "";
  if (display.length === 0) {
    rendered = chalk.inverse(" ");
  } else {
    for (let i = 0; i < display.length; i++) {
      rendered += i === displayCursor ? chalk.inverse(display[i]!) : display[i];
    }
    if (displayCursor >= display.length) {
      rendered += chalk.inverse(" ");
    }
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
