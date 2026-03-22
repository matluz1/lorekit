# Cruncher

Domain-agnostic TTRPG rules engine. Pure computation — no database, no network,
no state. Takes dataclasses in, returns dataclasses out.

Cruncher knows nothing about RPG concepts (classes, feats, hit points). All
domain knowledge lives in **system pack** JSON files. The engine only knows
variables, formulas, tables, and constraints.

## Install

```bash
pip install cruncher
```

Zero runtime dependencies.

## Quick Start

```python
import cruncher

# Load a system pack (directory of JSON files)
pack = cruncher.load_system_pack("path/to/pf2e/")

# Build a character
char = cruncher.CharacterData(
    name="Valeros",
    level=5,
    attributes={
        "stat": {"str": "18", "dex": "14", "con": "12"},
        "skill": {"skill_athletics": "2"},
    },
)

# Compute all derived stats (topo-sorted formulas)
result = cruncher.recalculate(pack, char)
print(result.derived)   # {"str_mod": 4, "melee_attack": 9, ...}
print(result.violations) # constraint check failures, if any

# Character construction (costs, budgets, progressions)
build = cruncher.process_build(
    "path/to/pf2e/",
    char.attributes,
    char.abilities,
    char.level,
)
print(build.attributes)  # {"hp_per_level": 10, "base_attack": 3, ...}
print(build.costs)       # {"powers": 45, ...}

# Roll dice (standard tabletop notation)
roll = cruncher.roll_expr("1d20+5")
print(roll["total"])     # 19

# Modifier stacking
policy = cruncher.load_stacking_policy(pack.stacking)
mods = [
    cruncher.ModifierEntry("bonus_defense", 2, bonus_type="circumstance"),
    cruncher.ModifierEntry("bonus_defense", 1, bonus_type="circumstance"),
    cruncher.ModifierEntry("bonus_defense", 3, bonus_type="status"),
]
net = cruncher.resolve_stacking(mods, policy)
print(net)  # {"bonus_defense": 5}  (max circumstance + sum status)
```

## Modules

| Module | What it does |
|--------|-------------|
| `cruncher.formulas` | Recursive-descent expression parser + evaluator. Functions: `floor`, `ceil`, `max`, `min`, `abs`, `sum`, `per`, `ratio`, `table`, `if`. |
| `cruncher.stacking` | Modifier stacking resolution. Groups by configurable field, applies max/sum rules per group. |
| `cruncher.system_pack` | Loads a system pack directory into a `SystemPack` dataclass. |
| `cruncher.engine` | Builds a formula context from character data, topo-sorts derived stat formulas, evaluates them, and validates constraints. |
| `cruncher.build` | Data-driven character construction: ranked purchases, source lookups (writes/effects/progressions), pipelines, arrays, sub-budgets. |
| `cruncher.dice` | Parses and rolls tabletop notation: `[N]d<sides>[kh<keep>][+/-mod]`. |

## System Packs

A system pack is a directory with a `system.json` and optional supporting
files. The engine reads formulas, defaults, tables, constraints, and build
rules from these files. Example structure:

```
pf2e/
├── system.json          Formulas, defaults, derived stats, build rules
├── classes/             Class progression tables
│   ├── fighter.json
│   └── wizard.json
├── feats.json           Feat definitions with effects
├── ancestries.json      Ancestry traits and bonuses
└── backgrounds.json     Background skill boosts
```

Cruncher does not ship system packs. You provide the path to your own, or use
the packs from the [LoreKit](https://github.com/erenes/lorekit) project.

## Key Types

```python
# Input: what you give cruncher
CharacterData(name, level, attributes, abilities, items)
SystemPack(name, dice, defaults, derived, tables, constraints, ...)
ModifierEntry(target_stat, value, bonus_type, source)

# Output: what cruncher gives back
CalcResult(derived, violations, changes)
BuildResult(attributes, costs, ability_costs, budget_total, budget_spent)
```

## Stacking Example

The stacking resolver is configured per system pack:

```json
{
  "stacking": {
    "group_by": "bonus_type",
    "positive": "max",
    "negative": "sum",
    "overrides": {
      "_none": {"positive": "sum", "negative": "sum"}
    }
  }
}
```

This says: group modifiers by `bonus_type`, keep only the highest positive
value per type, sum all negatives, but untyped modifiers (`_none`) always
stack by summing.

## Formula Language

Formulas are strings evaluated against a flat variable context:

```
floor((str - 10) / 2)                  # ability modifier
base_attack + str_mod + bonus_melee_attack   # derived stat
table(proficiency_bonus, level)         # table lookup by level
if(dex_mod > str_mod, dex_mod, str_mod) # conditional
per(level, 2)                           # ceiling division
```

Supported: `+`, `-`, `*`, `/`, comparisons (`<`, `>`, `<=`, `>=`, `==`, `!=`),
parentheses, dotted variable access, function calls.

## License

Apache 2.0
