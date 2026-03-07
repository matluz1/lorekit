/**
 * Simple file logger for GM/NPC streams.
 * Usage: tail -f data/gm.log  or  tail -f data/npc.log
 */
import { appendFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

let logDir: string = ".";

export function initLogger(projectRoot: string) {
  logDir = resolve(projectRoot, "data");
}

function ts(): string {
  return new Date().toISOString().slice(11, 23); // HH:MM:SS.mmm
}

function write(file: string, tag: string, text: string) {
  const line = `${ts()} [${tag}] ${text}\n`;
  appendFileSync(resolve(logDir, file), line);
}

export function clearLog(file: string) {
  try {
    writeFileSync(resolve(logDir, file), "");
  } catch {}
}

export function gmLog(tag: string, text: string) {
  write("gm.log", tag, text);
}

export function npcLog(tag: string, text: string) {
  write("npc.log", tag, text);
}
