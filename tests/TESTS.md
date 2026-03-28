# Test Strategy

## Directory structure

```
tests/
├── conftest.py          # shared fixtures (make_session, make_character, DB isolation)
├── fixtures/            # test data (test_system, test_system_area)
├── unit/                # single-module tests (fast, isolated)
└── integration/         # cross-module tests (multiple subsystems interacting)
```

```bash
pytest tests/unit/           # fast — single-module
pytest tests/integration/    # cross-module interactions
pytest                       # everything
```

## Current coverage (861 tests)

### Unit tests (`tests/unit/`)

| Area | Files | What it validates |
|------|-------|-------------------|
| **Cruncher** | `test_rules_formulas.py`, `test_stacking.py`, `test_rolldice.py`, `test_build_engine.py` | Pure computation: formulas, stacking resolution, dice, build engine |
| **Rules engine** | `test_rules_engine.py`, `test_auto_recalc.py`, `test_stacking_integration.py` | Derived stats, recalc chains, modifier stacking through DB |
| **Combat** | `test_combat_engine.py`, `test_mm3e_combat.py`, `test_combat_extensions.py`, `test_condition_enforcement.py`, `test_effect_resolution.py`, `test_on_hit_resist.py`, `test_gm_assisted.py`, `test_sustained_powers.py`, `test_free_actions.py`, `test_end_turn.py`, `test_encounter.py`, `test_ready_delay.py`, `test_switch_limit.py` | Action resolution, conditions, effects, powers, turn lifecycle, zones, movement |
| **NPC** | `test_npc_memory.py`, `test_npc_postprocess.py`, `test_npc_combat.py`, `test_npc_reflect.py`, `test_prefetch.py` | Memory scoring, response parsing, combat decisions, reflection, context assembly |
| **Narrative** | `test_session.py`, `test_story.py`, `test_character.py`, `test_region.py`, `test_timeline.py`, `test_journal.py`, `test_scope.py` | CRUD and business logic for each narrative module |
| **Checkpoint** | `test_checkpoint.py` | Save/load, undo/redo, branching, compression, deltas |
| **Search** | `test_recall.py` | Hybrid semantic + keyword search |
| **MCP tools** | `test_mcp_server.py`, `test_aggregates.py` | Tool functions through the MCP layer |
| **System packs** | `test_system_harness.py`, `test_pf2e_system.py`, `test_system_info.py` | Engine behavior across packs, pack content validation |
| **Infrastructure** | `test_init_db.py`, `test_ability_bridge.py` | Schema init, ability template bridge |

### Integration tests (`tests/integration/`)

| Area | Files | What it validates |
|------|-------|-------------------|
| **Combat + checkpoint** | `test_combat_checkpoint.py` | Save/load/revert preserves full encounter state (round, turn, zones, positions, HP, modifiers) across branches |

## What's missing (integration)

| Test scenario | What it catches |
|---------------|-----------------|
| Turn revert undoes NPC memories | `turn_save` → insert NPC memories → `turn_revert` → verify memories gone. Checkpoint captures NPC state correctly. |
| Entity auto-tagging | `turn_save` with character names in narration → verify `entry_entities` rows created. Tests the turn_save → extract_entities pipeline. |
| Rest clears modifiers | `combat_modifier` add → `rest` → verify modifier gone and stats restored. Tests the rest → clear → recalc pipeline. |
| NPC postprocess regression suite | Replay captured LLM responses (from real play sessions) through store → prefetch pipeline. Fixture-driven, no LLM calls. Catches parsing edge cases. |
| NPC memory accumulation | 5+ interactions of stored memories → verify prefetch still assembles correct context. Tests prefetch math under load. |
