# LoreKit

Tabletop RPG toolkit for AI agents. Tracks sessions, characters, dice rolls,
timeline events, regions, journal notes, and semantic recall. The agent reads
`GAMEMASTER_GUIDE.md` and runs the adventure as a gamemaster.

## Requirements

- Python 3.13+
- An AI agent with tool-use capabilities

## Setup

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python ./scripts/init_db.py
```

## Playing

Open your AI agent in the project directory and ask it to start a game.
The agent reads `GAMEMASTER_GUIDE.md` and takes it from there.

## File overview

| File | Purpose |
|------|---------|
| `GAMEMASTER_GUIDE.md` | Instructions for the AI agent acting as GM |
| `TOOLS.md` | Command reference for every script |
| `scripts/` | Game engine scripts (session, character, dice, journal, etc.) |
| `data/game.db` | SQLite database (created by `init_db.py`) |
| `data/chroma/` | ChromaDB vector store for semantic search |
