# Test Strategy

## Current coverage (740 tests)

| Layer | Files | What it validates |
|-------|-------|-------------------|
| **Unit — cruncher** | `test_rules_formulas.py`, `test_stacking.py`, `test_rolldice.py`, `test_build_engine.py` | Pure computation: formulas, stacking resolution, dice, build engine |
| **Unit — lorekit** | `test_rules_engine.py`, `test_combat_engine.py`, `test_npc_memory.py`, `test_npc_postprocess.py`, `test_npc_combat.py`, `test_system_info.py`, `test_init_db.py` | Single module behavior with DB |
| **Integration** | `test_auto_recalc.py`, `test_stacking_integration.py`, `test_prefetch.py`, `test_npc_reflect.py`, `test_checkpoint.py`, `test_recall.py` | Module interactions — recalc chains, memory scoring, checkpoint restore |
| **Combat** | `test_mm3e_combat.py`, `test_condition_enforcement.py`, `test_effect_resolution.py`, `test_gm_assisted.py`, `test_sustained_powers.py`, `test_end_turn.py`, `test_encounter.py` | Combat resolution, conditions, effects, sustained powers, turn lifecycle, zones |
| **MCP tool** | `test_mcp_server.py`, `test_aggregates.py` | Tool functions through the MCP layer (session_setup, character_build, etc.) |
| **System harness** | `test_system_harness.py` | Engine behavior parametrized across all system packs — combat flow, rest, initiative, HUD, templates |
| **System-specific** | `test_pf2e_system.py` | Pack content validation — formulas, progressions, class features |
| **Domain** | `test_session.py`, `test_story.py`, `test_character.py`, `test_region.py`, `test_timeline.py`, `test_journal.py` | CRUD and business logic for each narrative module |

## What's missing

### Functional tests (priority: high)

Tests that verify a *feature works from the GM's perspective* through MCP tools.
Each tests one feature through its public interface and verifies the observable output.

Unlike unit/integration tests, functional tests don't care about internals — they
call the MCP tool and check what comes back, the way the GM agent would.

| Feature | Test scenario | Why it matters |
|---------|--------------|----------------|
| NPC remembers across interactions | `npc_interact` twice → verify second prefetch includes memories from first | Validates the full post-process → store → prefetch pipeline |
| Critical hit in GM output | `rules_resolve` via MCP → verify "CRITICAL" in result string | MCP tool → engine → output formatting chain |
| Budget warning reaches GM | `character_sheet_update` with over-budget attrs → verify "WARNING" in response | MCP tool → rules_calc → build engine → output chain |
| Turn revert undoes NPC memories | `npc_interact` → `turn_save` → `npc_interact` → `turn_revert` → verify second memories gone | Checkpoint captures NPC state correctly |
| Reflection fires on timeskip | Build NPC with enough memories → `time_advance` 7+ days → verify reflection output | Auto-trigger fires through MCP tool |
| Entity auto-tagging | `turn_save` with character names in narration → verify `entry_entities` rows created | turn_save → extract_entities pipeline |
| NPC core evolves via state changes | `npc_interact` produces `[STATE_CHANGES]` → `character_view` shows updated emotional_state | Post-process → set_core → view pipeline |
| Rest clears modifiers | `combat_modifier` add → `rest` → verify modifier gone and stats restored | rest → clear → recalc pipeline |

### End-to-end tests (priority: medium)

Full play session simulations that exercise the GM workflow start to finish.
These depend on functional tests being solid — if a feature-level test fails,
the E2E test will fail in a confusing way deep in the scenario.

| Scenario | Flow |
|----------|------|
| Combat session | `session_setup` → `character_build` (PC + NPC) → `encounter_start` → `combat_modifier` → `rules_resolve` → `encounter_advance_turn` → `end_turn` → `encounter_end` → verify journal, checkpoints, modifier cleanup |
| RP session with NPC | `session_setup` → `character_build` (NPC with core) → `npc_interact` × 3 → verify memory accumulation → `time_advance` → verify reflection → `npc_interact` → verify reflection appears in prefetch |
| Turn save/revert cycle | `turn_save` → modify character + add memories → `turn_revert` → verify complete state restoration |

### Cruncher standalone tests (priority: medium)

Tests under `cruncher/tests/` that validate cruncher works without lorekit installed.
Currently all cruncher tests live in the main `tests/` directory and import lorekit
fixtures. A separate test suite would prove the package boundary is clean.

| Area | What to test |
|------|-------------|
| Formula evaluator | All functions, edge cases, error messages |
| Stacking | All policies, overrides, decomposition |
| Build engine | All operation types against test system pack |
| Engine | recalculate() with modifiers, topo sort, constraints |
| Dice | All notation variants, error cases |

### Property / fuzz tests (priority: low)

| Area | What to fuzz |
|------|-------------|
| Formula evaluator | Random valid formula strings → no crashes, deterministic output |
| Dice roller | All valid notations → results within bounds |
| Post-process parser | Malformed `[MEMORIES]` / `[STATE_CHANGES]` blocks → graceful fallback, no crash |
| Entity extraction | Unicode names, substring collisions, empty strings → no false positives |

## Order of implementation

1. **Functional tests** — highest value, catches composition bugs that unit tests miss
2. **Cruncher standalone tests** — proves the package boundary, enables independent CI
3. **E2E tests** — validates full workflows, debuggable because functional tests pinpoint which feature broke
4. **Property/fuzz tests** — hardens edge cases, lowest urgency
