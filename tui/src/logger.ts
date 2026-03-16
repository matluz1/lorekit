/**
 * Simple file logger for GM/NPC streams.
 * Usage: tail -f data/lorekit.log
 */
import { appendFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const LOG_FILE = "lorekit.log";

let logDir: string = ".";

export function initLogger(projectRoot: string) {
  logDir = resolve(projectRoot, "data");
}

function ts(): string {
  return new Date().toISOString().slice(11, 23); // HH:MM:SS.mmm
}

function write(source: string, tag: string, text: string) {
  const line = `${ts()} ${source} [${tag}] ${text}\n`;
  appendFileSync(resolve(logDir, LOG_FILE), line);
}

export function clearLog() {
  try {
    writeFileSync(resolve(logDir, LOG_FILE), "");
  } catch {}
}

export function gmLog(tag: string, text: string) {
  write("GM", tag, text);
}

export function npcLog(tag: string, text: string) {
  write("NPC", tag, text);
}
