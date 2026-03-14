# LoreKit

Tabletop RPG toolkit for AI agents. Tracks everything needed to run full
campaigns -- characters, sessions, story arcs, regions, and more.

All mechanical crunch is handled deterministically by the engine so the AI
never has to guess numbers. The GM agent reads `guidelines/GM_GUIDE.md` and
runs the adventure; NPCs are spawned as independent agents with their own
context and tool set.

## Requirements

- Python 3.13
- An AI agent with MCP support

## Setup

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The MCP server is configured in `.mcp.json`. On first use, the agent calls
`init_db` to create the database.

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
pre-commit install
```

## Testing

```bash
.venv/bin/pytest tests/
```

## Playing

```bash
npx tsx tui/src/index.tsx opus
```

The TUI launches the GM agent, which reads `guidelines/GM_GUIDE.md` and takes
it from there. All game tools are provided through the MCP server.

## Game Systems

LoreKit ships with two system packs under `systems/`:

| Directory | System                   | License  |
|-----------|--------------------------|----------|
| `pf2e`    | Pathfinder 2e Remaster   | ORC      |
| `mm3e`    | Mutants & Masterminds 3e | OGL 1.0a |

System packs are pure JSON. The rules engine is zero-knowledge: it only knows
variables, formulas, tables, and constraints. All domain logic lives in the
system pack files and the data-driven build engine.

Each pack ships a `test_config.json` alongside `system.json` so the
parametrized test harness can exercise the full combat flow, rest, initiative,
HUD, and encounter templates for that system. Packs without a config trigger a
pytest warning.

**System data is NOT covered by the project's Apache 2.0 license.** Each
system's data is governed by its own license, found in the `LICENSE` file
within that system's directory.

## File Overview

| Path | Purpose |
|------|---------|
| `guidelines/` | Agent guidelines (GM, NPC, shared) and tool references |
| `mcp_server.py` | MCP server -- primary interface to all game tools |
| `.mcp.json` | MCP server configuration (stdio, for the GM agent) |
| `.npc_mcp.json` | MCP server configuration (HTTP, for NPC agents) |
| `core/` | Game engine modules (session, character, rules, dice, etc.) |
| `systems/` | Game system packs (JSON definitions for PF2e, M&M3e) |
| `tests/` | Pytest test suite |
| `tui/` | Terminal UI (TypeScript/React/Ink) |
| `data/game.db` | SQLite database with vector embeddings (created by `init_db`) |
