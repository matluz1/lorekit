# Tests

Run with:

```bash
.venv/bin/pytest tests/
```

## Test categories

| Category | Files | What it tests |
|----------|-------|---------------|
| **Harness (parametrized)** | `test_system_harness.py` | Engine behavior across all system packs — combat flow, rest, initiative, HUD, templates |
| **System-agnostic** | `test_encounter.py`, `test_end_turn.py`, `test_stacking*.py` | Core mechanics via `COMBAT_CFG` dicts, no system pack dependency |
| **System-specific** | `test_pf2e_system.py`, `test_build_engine.py` | Pack content validation — formulas, progressions, class features, build rules |
| **Unit** | `test_rules_engine.py`, `test_rules_formulas.py`, `test_combat_engine.py` | Individual module behavior |
| **MCP integration** | `test_mcp_server.py`, `test_auto_recalc.py` | Tool functions end-to-end through the MCP layer |

## Fixtures

`fixtures/test_system/` is a minimal fake system pack with just enough
stats, formulas, and actions to test engine behavior without depending on a
real pack. Most system-agnostic and MCP integration tests use it.

## Conventions

- **Every test gets an isolated DB** — `conftest.py` sets `LOREKIT_DB` to a temp path (autouse fixture).
- **Use `make_session` / `make_character` factories** from `conftest.py`, not raw SQL.
- **New system packs** must ship a `test_config.json` alongside `system.json`. Packs without one trigger a pytest warning. See `test_system_harness.py` for the schema.
- **System-agnostic tests** should use `COMBAT_CFG` dicts and avoid importing system packs directly.
- **System-specific tests** go in their own file (e.g. `test_pf2e_system.py`). One file per pack.

## Adding a new system pack to the harness

1. Create `systems/<pack>/test_config.json` with:

```json
{
  "base_stats": {},
  "weapon_attrs": {},
  "resolution_type": "threshold or degree",
  "melee_action": "action name",
  "defense_stat": "derived stat name",
  "defense_bonus_key": "bonus stat for defense modifiers",
  "attack_stat": "derived stat name",
  "attack_bonus_key": "bonus stat for attack modifiers",
  "cover_zone_tag": "cover",
  "vital_current": "current HP/condition key",
  "vital_max": "max HP key or null"
}
```

2. Run `pytest tests/test_system_harness.py -v` — the new pack is auto-discovered.
