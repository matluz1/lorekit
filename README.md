# LoreKit

Open-source TTRPG game engine for AI agents. Tracks everything needed to run
full campaigns — characters, sessions, story arcs, regions, and more.

Play via the terminal TUI, or embed lorekit in your own app (Discord bot, web
client) using the GameSession Python API or the HTTP server. Under the hood,
lorekit starts an MCP server and spawns an AI agent as the GM — the client just
sends player messages and renders the responses.

All mechanical crunch is handled deterministically by the
[cruncher](cruncher/) engine so the AI never has to guess numbers. The GM
agent reads `guidelines/GM_GUIDE.md` and runs the adventure; NPCs are spawned
as independent agents with their own context and memory.

## Packages

This repo ships two Python packages:

| Package | Path | Description |
|---------|------|-------------|
| **cruncher** | `cruncher/` | Standalone, zero-dependency TTRPG rules engine. Pure computation — formulas, stacking, character building, stat derivation, dice. |
| **lorekit** | `src/lorekit/` | Full MCP game engine. Session management, characters, combat orchestration, NPC agents, narrative tracking, semantic search. Includes providers, orchestrator, config, and an optional HTTP server. Depends on cruncher. |

System packs (`systems/`) are data, not code — they ship separately from both
packages.

## Requirements

- Python 3.13+
- An AI CLI tool (e.g. Claude Code) — used by lorekit to run the GM agent
- Optional: `starlette` + `uvicorn` for the HTTP server (`pip install lorekit[server]`)

## Setup

```bash
uv sync

# or
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e cruncher/ -e .
```

Configuration lives in `~/.config/lorekit/config.toml`. On first run, lorekit
creates the database automatically.

## Development

```bash
uv sync --group dev
pre-commit install

# or
pip install -e ".[dev]"
pre-commit install
```

## Testing

```bash
pytest                       # all 1008 tests
pytest tests/unit/           # fast — single-module tests
pytest tests/integration/    # cross-module interaction tests
```

## Playing

Before playing, create `~/.config/lorekit/config.toml`:

```toml
[agent]
provider = "claude"
model = "opus"
```

**TUI** (terminal interface):

```bash
make tui
```

Or directly: `npx tsx examples/tui/src/index.tsx`

The TUI launches the GM agent, which reads `guidelines/GM_GUIDE.md` and takes
it from there. All game tools are provided through the MCP server.

**HTTP server** (for web clients or custom frontends):

```bash
make serve
```

**Python API** (embed lorekit in your own application):

```python
from lorekit.orchestrator import GameSession

session = GameSession(campaign_dir="~/my-campaign")
async for event in session.send("I search the room for traps"):
    print(event)
```

## Project Structure

```
lorekit/
├── cruncher/                 Pure rules engine (pip install cruncher)
│   └── src/cruncher/
│       ├── formulas.py       Expression parser + evaluator
│       ├── stacking.py       Modifier stacking resolution
│       ├── system_pack.py    SystemPack loader (JSON → dataclass)
│       ├── engine.py         Derived stat computation (topo-sorted)
│       ├── build.py          Data-driven character construction
│       ├── dice.py           Tabletop dice notation
│       └── types.py          CharacterData, error types
│
├── src/lorekit/              Full game engine (pip install lorekit)
│   ├── server.py             MCP server — 51 tools for the GM agent
│   ├── providers/            Agent provider abstraction
│   │   ├── base.py           StreamChunk, GameEvent, AgentProcess, AgentProvider
│   │   └── claude/           Claude CLI provider (JSONL parser, process management)
│   ├── config.py             Platform-aware TOML configuration
│   ├── orchestrator.py       GameSession — public Python API
│   ├── http_server.py        HTTP + SSE server (optional, requires lorekit[server])
│   ├── rules.py              DB glue: load → cruncher → write back
│   ├── combat/               Action resolution, conditions, turn lifecycle
│   ├── encounter.py          Zone-based positioning, movement, initiative
│   ├── rest.py               Rest rules orchestration
│   ├── character.py          Character CRUD
│   ├── db.py                 SQLite schema, migrations, utilities
│   ├── npc/                  NPC agent subsystem
│   │   ├── memory.py         Park+ACT-R memory scoring
│   │   ├── combat.py         NPC combat decision orchestration
│   │   ├── reflect.py        LLM-driven reflection generation
│   │   ├── prefetch.py       Deterministic context assembly
│   │   └── postprocess.py    Response parsing + state extraction
│   ├── narrative/            Session & story state
│   │   ├── session.py, story.py, timeline.py, journal.py
│   │   ├── time.py           Narrative clock
│   │   └── region.py         Hierarchical regions
│   └── support/              Persistence & search
│       ├── checkpoint.py     Branching save/load with compression + deltas
│       ├── export.py         Human-readable session export
│       ├── recall.py         Hybrid semantic + keyword search
│       └── vectordb.py       sqlite-vec embeddings
│
├── systems/                  Game system packs (JSON, separate licensing)
│   ├── pf2e/                 Pathfinder 2e Remaster (ORC)
│   └── mm3e/                 d20 Hero SRD 3e (OGL 1.0a)
│
├── guidelines/               Agent guidelines (GM, NPC, shared)
├── tests/                    1008 tests (unit/ + integration/)
├── examples/                 Reference client implementations
│   └── tui/                  Terminal UI (TypeScript/React/Ink)
├── Makefile                  Common tasks (tui, serve, test, lint)
└── ~/.config/lorekit/        Default data location (db, config.toml)
```

## Game Systems

LoreKit ships with two system packs under `systems/`:

| Directory | System                   | License  |
|-----------|--------------------------|----------|
| `pf2e`    | Pathfinder 2e Remaster             | ORC      |
| `mm3e`    | d20 Hero SRD (3e)                  | OGL 1.0a |

System packs are pure JSON. The rules engine is domain-agnostic: it only knows
variables, formulas, tables, and constraints. All domain logic lives in the
system pack files and the data-driven build engine.

Each pack ships a `test_config.json` alongside `system.json` so the
parametrized test harness can exercise the full combat flow, rest, initiative,
HUD, and encounter templates for that system. Packs without a config trigger a
pytest warning.

**System data is NOT covered by the project's Apache 2.0 license.** Each
system's data is governed by its own license, found in the `LICENSE` file
within that system's directory.
