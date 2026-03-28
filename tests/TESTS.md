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

## Current coverage (876 tests)

### Unit tests (`tests/unit/`) — 856 tests

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

### Integration tests (`tests/integration/`) — 20 tests

| Area | Files | What it validates |
|------|-------|-------------------|
| **Combat + checkpoint** | `test_combat_checkpoint.py` | Save/load/revert preserves full encounter state (round, turn, zones, positions, HP, modifiers) across branches |
| **NPC + checkpoint** | `test_npc_checkpoint.py` | Turn revert undoes NPC memories and restores npc_core identity |
| **Entity tagging** | `test_entity_tagging.py` | turn_save auto-tags character and region names in narration via entry_entities |
| **Rest + modifiers** | `test_rest_modifiers.py` | Short/long rest clears combat modifiers by duration type and restores HP |
| **NPC postprocess** | `test_npc_postprocess_regression.py` | Parses [MEMORIES] and [STATE_CHANGES] blocks, stores memories, applies core updates, fallback on missing blocks |
| **NPC prefetch** | `test_npc_prefetch_accumulation.py` | Context assembly respects token budget, includes high-importance memories, boosts entity-matched memories, includes core identity |
