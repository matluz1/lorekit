/**
 * Read-only SQLite access for sidebar display data.
 * All writes go through the LLM provider → MCP → mcp_server.py.
 */
import Database from "better-sqlite3";
import { resolve, dirname } from "node:path";
import { mkdirSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";

let db: Database.Database | null = null;

export function openDb(projectRoot: string) {
  const dbPath = resolve(projectRoot, "data", "game.db");
  if (!existsSync(dbPath)) {
    mkdirSync(dirname(dbPath), { recursive: true });
    const python = resolve(projectRoot, ".venv/bin/python");
    execFileSync(python, ["core/init_db.py"], { cwd: projectRoot });
  }
  db = new Database(dbPath, { readonly: true });
}

export function closeDb() {
  db?.close();
  db = null;
}

// ── Types ──────────────────────────────────────────────

export interface Session {
  id: number;
  name: string;
  setting: string;
  system_type: string;
  status: string;
}

export interface Character {
  id: number;
  name: string;
  level: number;
  status: string;
  type: string;
  region_id: number | null;
}

export interface CharAttribute {
  category: string;
  key: string;
  value: string;
}

export interface InventoryItem {
  id: number;
  name: string;
  description: string;
  quantity: number;
  equipped: number;
}

export interface Ability {
  name: string;
  description: string;
  category: string;
  uses: string;
}

export interface Region {
  id: number;
  name: string;
  description: string;
}

export interface TimelineEntry {
  id: number;
  entry_type: string;
  content: string;
  summary: string;
  created_at: string;
}

// ── Queries ────────────────────────────────────────────

export function getActiveSessions(): Session[] {
  return db!
    .prepare(
      "SELECT id, name, setting, system_type, status FROM sessions WHERE status = 'active' ORDER BY id"
    )
    .all() as Session[];
}

export function getPC(sessionId: number): Character | undefined {
  return db!
    .prepare(
      "SELECT id, name, level, status, type, region_id FROM characters WHERE session_id = ? AND type = 'pc' LIMIT 1"
    )
    .get(sessionId) as Character | undefined;
}

export function getCharAttributes(characterId: number): CharAttribute[] {
  return db!
    .prepare(
      "SELECT category, key, value FROM character_attributes WHERE character_id = ? ORDER BY category, key"
    )
    .all(characterId) as CharAttribute[];
}

export function getInventory(characterId: number): InventoryItem[] {
  return db!
    .prepare(
      "SELECT id, name, description, quantity, equipped FROM character_inventory WHERE character_id = ?"
    )
    .all(characterId) as InventoryItem[];
}

export function getAbilities(characterId: number): Ability[] {
  return db!
    .prepare(
      "SELECT name, description, category, uses FROM character_abilities WHERE character_id = ?"
    )
    .all(characterId) as Ability[];
}

export function getRegion(regionId: number): Region | undefined {
  return db!
    .prepare("SELECT id, name, description FROM regions WHERE id = ?")
    .get(regionId) as Region | undefined;
}

export function getRegionNPCs(
  regionId: number,
  sessionId: number
): Character[] {
  return db!
    .prepare(
      "SELECT id, name, level, status, type, region_id FROM characters WHERE session_id = ? AND type = 'npc' AND region_id = ? AND status = 'alive'"
    )
    .all(sessionId, regionId) as Character[];
}

export function getTimeline(
  sessionId: number,
  last: number = 5
): TimelineEntry[] {
  return db!
    .prepare(
      "SELECT id, entry_type, content, summary, created_at FROM timeline WHERE session_id = ? ORDER BY id DESC LIMIT ?"
    )
    .all(sessionId, last) as TimelineEntry[];
}

// ── NPC queries ───────────────────────────────────────

export function getCharacter(characterId: number): Character | undefined {
  return db!
    .prepare(
      "SELECT id, name, level, status, type, region_id FROM characters WHERE id = ?"
    )
    .get(characterId) as Character | undefined;
}

export function getSession(sessionId: number): Session | undefined {
  return db!
    .prepare(
      "SELECT id, name, setting, system_type, status FROM sessions WHERE id = ?"
    )
    .get(sessionId) as Session | undefined;
}

export function getNPCsByName(
  sessionId: number,
  name: string
): Character[] {
  return db!
    .prepare(
      "SELECT id, name, level, status, type, region_id FROM characters WHERE session_id = ? AND type = 'npc' AND name LIKE ? AND status = 'alive'"
    )
    .all(sessionId, `%${name}%`) as Character[];
}

// ── Sidebar aggregate ──────────────────────────────────

export interface SidebarData {
  pc: Character;
  attrs: CharAttribute[];
  inventory: InventoryItem[];
  abilities: Ability[];
  region?: Region;
  regionNPCs: Character[];
  timeline: TimelineEntry[];
}

export function getSidebarData(
  sessionId: number
): SidebarData | null {
  try {
    const pc = getPC(sessionId);
    if (!pc) return null;
    return {
      pc,
      attrs: getCharAttributes(pc.id),
      inventory: getInventory(pc.id),
      abilities: getAbilities(pc.id),
      region: pc.region_id ? getRegion(pc.region_id) : undefined,
      regionNPCs: pc.region_id
        ? getRegionNPCs(pc.region_id, sessionId)
        : [],
      timeline: getTimeline(sessionId, 5),
    };
  } catch {
    return null;
  }
}
