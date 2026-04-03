/**
 * Buffered async file logger for GM/NPC streams.
 * Batches writes to disk every FLUSH_INTERVAL_MS to avoid blocking the
 * event loop with synchronous I/O on every log call.
 *
 * Usage: tail -f data/lorekit.log
 */
import { appendFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const LOG_FILE = "lorekit.log";
const FLUSH_INTERVAL_MS = 200;

let logDir: string = ".";
let buffer: string[] = [];
let flushTimer: ReturnType<typeof setInterval> | null = null;

function logPath(): string {
  return resolve(logDir, LOG_FILE);
}

function ts(): string {
  return new Date().toISOString().slice(11, 23); // HH:MM:SS.mmm
}

async function flush() {
  if (buffer.length === 0) return;
  const batch = buffer.join("");
  buffer = [];
  try {
    await appendFile(logPath(), batch);
  } catch {}
}

export function initLogger(projectRoot: string) {
  logDir = resolve(projectRoot, "data");
  if (!flushTimer) {
    flushTimer = setInterval(flush, FLUSH_INTERVAL_MS);
    // Don't keep process alive just for logging
    flushTimer.unref();
  }
}

function write(source: string, tag: string, text: string) {
  buffer.push(`${ts()} ${source} [${tag}] ${text}\n`);
}

export async function clearLog() {
  buffer = [];
  try {
    await writeFile(logPath(), "");
  } catch {}
}

export function gmLog(tag: string, text: string) {
  write("GM", tag, text);
}

export function npcLog(tag: string, text: string) {
  write("NPC", tag, text);
}

/** Flush remaining buffer (call before exit). */
export async function flushLog() {
  if (flushTimer) {
    clearInterval(flushTimer);
    flushTimer = null;
  }
  await flush();
}
