# LoreKit

Tabletop RPG toolkit for AI agents. Tracks sessions, characters, dice rolls,
timeline events, regions, journal notes, and semantic recall. The agent reads
`GAMEMASTER_GUIDE.md` and runs the adventure as a gamemaster.

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

## Playing

Open your AI agent in the project directory and ask it to start a game.
The agent reads `GAMEMASTER_GUIDE.md` and takes it from there. All game
tools are provided through the MCP server -- no manual script invocation
needed.

## File overview

| File | Purpose |
|------|---------|
| `GAMEMASTER_GUIDE.md` | Instructions for the AI agent acting as GM |
| `TOOLS.md` | Reference for every MCP tool |
| `mcp_server.py` | MCP server -- primary interface to all game tools |
| `.mcp.json` | MCP server configuration |
| `scripts/` | Game engine (session, character, dice, journal, etc.) |
| `data/game.db` | SQLite database (created by `init_db`) |
| `data/chroma/` | ChromaDB vector store for semantic search |
