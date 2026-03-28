# LoreKit

Tabletop RPG toolkit for AI agents. Tracks everything needed to run full
campaigns — characters, sessions, story arcs, regions, and more.

All mechanical crunch is handled deterministically by the
[cruncher](cruncher/) engine so the AI never has to guess numbers. The GM
agent reads `guidelines/GM_GUIDE.md` and runs the adventure; NPCs are spawned
as independent agents with their own context and memory.

## Packages

This repo ships two Python packages:

| Package | Path | Description |
|---------|------|-------------|
| **cruncher** | `cruncher/` | Standalone, zero-dependency TTRPG rules engine. Pure computation — formulas, stacking, character building, stat derivation, dice. |
| **lorekit** | `src/lorekit/` | Full MCP game engine. Session management, characters, combat orchestration, NPC agents, narrative tracking, semantic search. Depends on cruncher. |

System packs (`systems/`) are data, not code — they ship separately from both
packages.

## Requirements

- Python 3.13+
- An AI agent with MCP support (e.g. Claude Code)

## Setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e cruncher/ -e .
```

The MCP server is configured in `.mcp.json`. On first use, the agent calls
`init_db` to create the database.

## Development

```bash
pip install -r requirements-dev.txt
pre-commit install
```

## Testing

```bash
pytest                       # all 876 tests
pytest tests/unit/           # fast — single-module tests
pytest tests/integration/    # cross-module interaction tests
```

## Playing

```bash
npx tsx tui/src/index.tsx opus
```

The TUI launches the GM agent, which reads `guidelines/GM_GUIDE.md` and takes
it from there. All game tools are provided through the MCP server.

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
├── tests/                    876 tests (unit/ + integration/)
├── tui/                      Terminal UI (TypeScript/React/Ink)
└── data/game.db              SQLite database (created by init_db)
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
