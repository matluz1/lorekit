# LoreKit

Tabletop RPG toolkit for AI agents. Tracks everything needed to run full
campaigns -- characters, sessions, story arcs, regions, and more.

All mechanical crunch is handled deterministically by the engine so the AI
never has to guess numbers. The GM agent reads `GAMEMASTER_GUIDE.md` and
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

## Testing

```bash
.venv/bin/pytest tests/ -v
```

## Playing

Open your AI agent in the project directory and ask it to start a game.
The agent reads `GAMEMASTER_GUIDE.md` and takes it from there. All game
tools are provided through the MCP server -- no manual script invocation
needed.

## Game Systems

LoreKit ships with two system packs under `systems/`:

| Directory | System                   | License  |
|-----------|--------------------------|----------|
| `pf2e`    | Pathfinder 2e Remaster   | ORC      |
| `mm3e`    | Mutants & Masterminds 3e | OGL 1.0a |

System packs are pure JSON. The rules engine is zero-knowledge: it only knows
variables, formulas, tables, and constraints. All domain logic lives in the
system pack files and the data-driven build engine.

**System data is NOT covered by the project's Apache 2.0 license.** Each
system's data is governed by its own license, found in the `LICENSE` file
within that system's directory.

## File Overview

| Path | Purpose |
|------|---------|
| `GAMEMASTER_GUIDE.md` | Instructions for the AI agent acting as GM |
| `SHARED_GUIDE.md` | Rules shared by all participants (GM and NPCs) |
| `NPC_GUIDE.md` | Instructions for NPC agents |
| `TOOLS.md` | Reference for every MCP tool |
| `NPC_TOOLS.md` | Restricted tool set available to NPCs |
| `mcp_server.py` | MCP server -- primary interface to all game tools |
| `.mcp.json` | MCP server configuration (stdio, for the GM agent) |
| `.npc_mcp.json` | MCP server configuration (HTTP, for NPC agents) |
| `core/` | Game engine modules (session, character, rules, dice, etc.) |
| `systems/` | Game system packs (JSON definitions for PF2e, M&M3e) |
| `tests/` | Pytest test suite |
| `tui/` | Terminal UI (TypeScript/React/Ink) |
| `data/game.db` | SQLite database with vector embeddings (created by `init_db`) |
