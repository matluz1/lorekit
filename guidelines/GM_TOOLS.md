# LoreKit -- GM Tool Reference

This file documents every tool available to the Game Master. Read this
before using anything.

All tools are called via the LoreKit MCP server. The database is
auto-created on first access — no manual initialization needed.

Errors are returned as text starting with `ERROR:`.

All character-facing tools accept character names (case-insensitive)
in addition to numeric IDs.

Tools are organized into two groups:
- **Aggregate tools** (recommended) — high-level wrappers that combine common
  multi-step workflows into single calls. Use these by default.
- **Domain tools** — individual operations organized by domain. Use these when
  you need to do something the aggregates don't cover.

---

## Aggregate Tools

These tools combine common multi-step workflows into single calls. Prefer
these over calling individual tools separately.

---

### turn_save

Save a game turn: narration + player choice + last_gm_message in one call.

```
turn_save(session_id=1, narration="<exact text shown to player>", summary="<1-2 sentence summary>", player_choice="<player's exact message>")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| narration | str | no | "" | GM narration text (exact text shown to player) |
| summary | str | no | "" | 1-2 sentence summary for semantic search |
| player_choice | str | no | "" | Player's exact message |
| narrative_time | str | no | "" | Override in-game timestamp (ISO 8601). If omitted, uses current narrative clock. |

At least one of narration or player_choice is required.

**Output:**
```
TIMELINE_ADDED: 42
META_SET: last_gm_message
TIMELINE_ADDED: 43
```

---

### character_build

Create a full character in one call: identity + attributes + items + abilities.

```
character_build(session=1, name="Aldric", level=3, type="pc", attrs='[{"category":"stat","key":"strength","value":"16"}]', items='[{"name":"Longsword","desc":"A fine steel blade","qty":1,"equipped":1}]', abilities='[{"name":"Second Wind","desc":"Regain 1d10+level HP","category":"feat","uses":"1/rest"}]')
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session | int | yes | | Session ID |
| name | str | yes | | Character name |
| level | int | yes | | Character level |
| type | str | no | "pc" | pc or npc |
| region | int | no | 0 | Region ID (0 = none) |
| attrs | str | no | "[]" | JSON array of {category, key, value} objects |
| items | str | no | "[]" | JSON array of {name, desc?, qty?, equipped?} objects |
| abilities | str | no | "[]" | JSON array of {name, desc, category, uses?} objects |

**Output:**
```
CHARACTER_BUILT: 1 (attrs=6, items=3, abilities=2)
```

---

### session_setup

Set up an entire session in one call: session + metadata + story + acts + regions.

```
session_setup(name="The Dark Forest", setting="dark fantasy", system="d20 fantasy", meta='{"language":"English"}', story_size="short", story_premise="A cursed forest threatens the village", acts='[{"title":"The Call","goal":"Reach the temple","event":"The temple collapses"}]', regions='[{"name":"Ashar","desc":"A village","children":[{"name":"Market Square"}]}]')
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| name | str | yes | | Adventure name |
| setting | str | yes | | World setting |
| system | str | yes | | Rule system archetype |
| meta | str | no | "{}" | JSON object of key-value metadata pairs |
| story_size | str | no | "" | oneshot, short, or campaign |
| story_premise | str | no | "" | One-line story premise |
| acts | str | no | "[]" | JSON array of {title, desc?, goal?, event?} objects |
| regions | str | no | "[]" | JSON array of {name, desc?, children?} objects (recursive) |
| narrative_time | str | no | "" | Initial in-game time (ISO 8601, e.g. "1347-03-15T14:00") |

The first act is automatically set to "active".

**Output:**
```
SESSION_CREATED: 1
META_SET: 1 keys
STORY_SET: 1
ACTS_ADDED: 3 (first act set to active)
REGIONS_CREATED: 4
```

---

### session_resume

Assemble full context for resuming a session in one call. Returns session
details, narrative time, metadata, active story act, all PCs with full sheets,
all regions, last 20 timeline entries, and last 5 journal notes.

```
session_resume(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output:** A structured context packet with sections:
```
=== SESSION ===
(session details)

=== METADATA ===
(all key-value pairs)

=== NARRATIVE TIME ===
CURRENT: 1347-03-15T14:00

=== STORY ===
(premise, acts, active act details)

=== PLAYER CHARACTERS ===
(full character sheets for all PCs)

=== REGIONS ===
(all regions)

=== RECENT TIMELINE (last 20) ===
(last 20 timeline entries)

=== RECENT JOURNAL (last 5) ===
(last 5 journal notes)
```

---

### character_sheet_update

Batch update a character: level/status/region + attributes + items + abilities + remove items.

```
character_sheet_update(character_id=1, level=4, attrs='[{"category":"combat","key":"hp","value":"35"}]', items='[{"name":"Health Potion","qty":2}]', remove_items='["Rusty Sword"]')
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| character_id | int | yes | | Character ID |
| level | int | no | 0 | New level (0 = unchanged) |
| status | str | no | "" | New status |
| region | int | no | 0 | New region ID (0 = unchanged) |
| attrs | str | no | "[]" | JSON array of {category, key, value} objects |
| items | str | no | "[]" | JSON array of {name, desc?, qty?, equipped?} objects |
| abilities | str | no | "[]" | JSON array of {name, desc, category, uses?} objects |
| remove_items | str | no | "[]" | JSON array of item names (strings) or item IDs (integers) |

**Output:**
```
CHARACTER_UPDATED: 1
ATTRS_SET: 2
ITEMS_REMOVED: 1
ITEMS_SET: 1
```

---

## Narrative Time

## time_get

Get the current in-game narrative time.

```
time_get(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output:**
```
NARRATIVE_TIME: 1347-03-15T14:00
```

If not set: `NARRATIVE_TIME: (not set)`.

Set the initial time via `session_setup(narrative_time="...")`.

## time_advance

Advance the in-game clock by a given amount. Automatically triggers NPC
reflection when the timeskip is >= 7 days.

```
time_advance(session_id=1, amount=3, unit="hours")
time_advance(session_id=1, amount=7, unit="days")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| amount | int | yes | How much to advance |
| unit | str | yes | minutes, hours, days, weeks, months, years |

**Output:**
```
TIME_ADVANCED: 1347-03-15T14:00 → 1347-03-15T17:00 (+3 hours)
```

**Output (large timeskip with reflections):**
```
TIME_ADVANCED: 1347-03-15T14:00 → 1347-03-22T14:00 (+7 days)
REFLECTIONS: Reflected on 2 NPCs (Roderick: 3 insights, Mira: 2 insights). Skipped 1 NPCs below threshold.
```

Narrative time must be set first (via `time_set` or `session_setup`).

---

## Dice

## roll_dice

Roll dice using standard tabletop notation. Accepts one or more expressions
separated by spaces.

```
roll_dice(expression="<expr> [expr ...]")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| expression | str | yes | Dice expression(s), space-separated |

**Expression format:** `[N]d<sides>[kh<keep>][+/-<modifier>]`

| Part | Meaning | Required | Example |
|------|---------|----------|---------|
| N | Number of dice (default 1) | No | `3` in `3d6` |
| d\<sides\> | Die type | Yes | `d20`, `d6`, `d100` |
| kh\<keep\> | Keep highest N dice | No | `kh3` in `4d6kh3` |
| +/-\<mod\> | Add/subtract a flat number | No | `+5` in `2d8+5` |

**Examples:**
```
roll_dice(expression="d20")
roll_dice(expression="3d6")
roll_dice(expression="2d8+5")
roll_dice(expression="4d6kh3")
roll_dice(expression="d20 2d6+3 4d6kh3")
```

**Output format (single expression):**
```
ROLLS: 4,3,6,2
KEPT: 6,4,3
MODIFIER: +0
TOTAL: 13
```

**Output format (multiple expressions):**
```
--- d20 ---
ROLLS: 14
KEPT: 14
MODIFIER: +0
TOTAL: 14

--- 2d8+5 ---
ROLLS: 3,7
KEPT: 3,7
MODIFIER: +5
TOTAL: 15
```

| Line | Meaning |
|------|---------|
| ROLLS | Every die result, comma-separated |
| KEPT | Which dice count toward the total (all of them unless kh is used) |
| MODIFIER | The flat modifier applied (+0 if none) |
| TOTAL | Final result: sum of kept dice + modifier |

---

## Session

## session_list

List sessions. Optionally filter by status.

```
session_list()
session_list(status="active")
session_list(status="finished")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| status | str | no | "" | Filter: active or finished |

**Output:** table with columns `id, name, setting, system_type, status, created_at`.

## session_update

Update session status. When status is set to `"finished"`, automatically
triggers NPC reflection on all NPCs regardless of threshold.

```
session_update(session_id=1, status="finished")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| status | str | yes | New status |

**Output:**
```
SESSION_UPDATED: 1
```

**Output (finishing session with reflections):**
```
SESSION_UPDATED: 1
REFLECTIONS: Reflected on 3 NPCs (Roderick: 2 insights, Mira: 3 insights, Elder: 1 insights).
```

## session_meta_set

Store freeform key-value data on a session (house rules, world lore, etc.).
Overwrites the value if the key already exists.

```
session_meta_set(session_id=1, key="house_rule_crits", value="Max damage on nat 20")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| key | str | yes | Metadata key |
| value | str | yes | Metadata value |

**Output:**
```
META_SET: house_rule_crits
```

## session_meta_get

Get session metadata. If key is empty, returns all metadata.

```
session_meta_get(session_id=1)
session_meta_get(session_id=1, key="house_rule_crits")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| key | str | no | "" | Specific key, or empty for all |

Single key output:
```
house_rule_crits: Max damage on nat 20
```

All keys output: table with columns `key, value`.

---

## Story

## story

Manage story plan and acts. All story operations go through this single tool
with an `action` parameter.

```
story(action="set", session_id=1, size="short", premise="A cursed forest threatens the village")
story(action="view", session_id=1)
story(action="view", session_id=1, act_id=2)
story(action="add_act", session_id=1, title="The Call", goal="Reach the temple", event="The temple collapses")
story(action="update_act", act_id=1, status="skipped")
story(action="advance", session_id=1)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| action | str | yes | | `set`, `view`, `add_act`, `update_act`, or `advance` |
| session_id | int | varies | 0 | Required for set, view, add_act, advance |
| act_id | int | varies | 0 | Required for update_act; optional for view |
| size | str | no | "" | Story size (for set): oneshot, short, campaign |
| premise | str | no | "" | Story premise (for set) |
| title | str | no | "" | Act title (for add_act, update_act) |
| desc | str | no | "" | Act description |
| goal | str | no | "" | Act goal |
| event | str | no | "" | Act turning point |
| status | str | no | "" | Act status (for update_act) |

---

## Character

## character_view

Shows the full character sheet: identity, attributes, inventory, and abilities.

```
character_view(character_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| character_id | int | yes | Character ID |

**Output:**
```
ID: 1
SESSION: 1
NAME: Aldric
TYPE: pc
LEVEL: 3
STATUS: alive
REGION:
CREATED: 2026-02-21T16:00:00Z

--- ATTRIBUTES ---
category  key           value
--------  ------------  -----
stat      strength      16

--- INVENTORY ---
id  name       description         quantity  equipped
--  ---------  ------------------  --------  --------
1   Longsword  A fine steel blade  1         1

--- ABILITIES ---
id  name         category  uses    description
--  -----------  --------  ------  -----------
1   Second Wind  feat      1/rest  Regain 1d10+level HP
```

## character_list

List characters in a session.

```
character_list(session=1)
character_list(session=1, type="npc")
character_list(session=1, type="npc", region=1)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session | int | yes | | Session ID |
| type | str | no | "" | Filter: pc or npc |
| region | int | no | 0 | Filter by region ID |

**Output:** table with columns `id, name, type, level, status`.

---

## Region

## region

Manage regions in a session. All region operations go through this single tool
with an `action` parameter.

```
region(action="create", session_id=1, name="Ashar", desc="A shepherds' village")
region(action="create", session_id=1, name="Dockside", desc="Harbor quarter", parent_id=1)
region(action="list", session_id=1)
region(action="view", region_id=1)
region(action="update", region_id=1, name="Ashar (ruins)", desc="The village was destroyed")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| action | str | yes | | `create`, `list`, `view`, or `update` |
| session_id | int | varies | 0 | Required for create, list |
| region_id | int | varies | 0 | Required for view, update |
| name | str | no | "" | Region name (for create, update) |
| desc | str | no | "" | Description (for create, update) |
| parent_id | int | no | 0 | Parent region ID for nesting (for create, update) |

---

## Timeline

## timeline_set_summary

Set the summary for an existing timeline entry. Use this to backfill
summaries on older entries that were created without one.

```
timeline_set_summary(timeline_id=42, summary="<1-2 sentence summary>")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| timeline_id | int | yes | Timeline entry ID |
| summary | str | yes | 1-2 sentence summary |

**Output:**
```
SUMMARY_SET: 42
```

## turn_revert

Revert the last saved turn. Restores **all** game state — characters, items,
attributes, abilities, story acts, regions, session metadata — and removes
timeline/journal entries created since the previous checkpoint. Each
`turn_save` creates a checkpoint; `turn_revert` pops the latest one and
restores the previous.

```
turn_revert(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output:**
```
TURN_REVERTED: restored to checkpoint #3 (2 timeline, 1 journal entries removed)
```

## timeline_list

List timeline entries.

```
timeline_list(session_id=1)
timeline_list(session_id=1, type="narration")
timeline_list(session_id=1, last=10)
timeline_list(session_id=1, id="42")
timeline_list(session_id=1, id="10-20")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| type | str | no | "" | narration or player_choice |
| last | int | no | 0 | Limit to last N entries |
| id | str | no | "" | Single ID `"42"` or range `"10-20"` (ignores type/last) |

**Output:** table with columns `id, entry_type, content, created_at`.
Ordered oldest first.

---

## Journal

## journal_add

Add a journal entry. Use for GM notes, not in-game events.

```
journal_add(session_id=1, type="note", content="Player prefers non-combat solutions")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| type | str | yes | | event, combat, discovery, npc, decision, note |
| content | str | yes | | Entry text |
| narrative_time | str | no | "" | Override in-game timestamp. If omitted, uses current narrative clock. |

**Output:**
```
JOURNAL_ADDED: 1
```

## journal_list

List journal entries.

```
journal_list(session_id=1)
journal_list(session_id=1, type="note")
journal_list(session_id=1, last=5)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| type | str | no | "" | Filter by entry type |
| last | int | no | 0 | Limit to last N entries |

**Output:** table with columns `id, entry_type, content, created_at`.
Ordered newest first.

---

## NPC

## npc_interact

Interact with an NPC in character. Spawns an ephemeral AI process that uses
the NPC's personality, attributes, inventory, abilities, and recent timeline
to generate an in-character response. The NPC can speak, roll dice, and
search past events for context.

```
npc_interact(session_id=1, npc_id=3, message="The player asks the elder about the curse on the forest.")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| npc_id | int | yes | NPC character ID |
| message | str | yes | Situation description and what the PC said |

The `message` should describe the context and the player's words. The tool
returns the NPC's in-character response as plain text.

**Output (success):**
```
"The curse? Aye, it started three winters ago when the stone was taken from the shrine. You'd do well to stay out of those woods after dark."
```

**Output (NPC not found):**
```
ERROR: NPC #99 not found in session #1
```

The NPC gets all relevant context (personality, attributes, inventory,
abilities, recent timeline) baked into its system prompt. Each call is
independent — there is no persistent NPC process.

## npc_combat_turn

Execute a full NPC combat turn in one call: decision + movement + action +
advance initiative.

```
npc_combat_turn(session_id=1, npc_id=3)
npc_combat_turn(session_id=1, npc_id="Goblin")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| npc_id | int/str | yes | NPC character ID or name |

The tool:
1. Builds combat context (positions, relative health, available actions)
2. Asks the NPC agent for a structured decision (action, target, movement)
3. Executes: move → resolve action → advance turn (auto end_turn)

Supports narrative-only turns when the NPC chooses no mechanical action.

## npc_reflect

Trigger reflection for a single NPC. Synthesizes accumulated memories into
higher-order insights, behavioral rules, and identity updates.

Reflection is also triggered automatically by:
- `time_advance` when the timeskip is >= 7 days
- `session_update` when status is set to `"finished"` (reflects all NPCs)

```
npc_reflect(session_id=1, npc_id=3)
npc_reflect(session_id=1, npc_id="Roderick")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| npc_id | int/str | yes | NPC character ID or name |

**Output:**
```
NPC_REFLECTED: Roderick — 3 reflections, 1 behavioral rules
```

The tool:
1. Gathers unprocessed memories (since the NPC's last reflection)
2. Sends them to an LLM along with the NPC's identity
3. Stores resulting insights as `reflection` type memories
4. Merges new behavioral rules into `npc_core.behavioral_patterns`
5. Applies identity updates (self_concept, goals, emotional_state) if warranted
6. Prunes very old, unimportant, never-accessed memories (> 38 days, importance < 0.3)

---

## Rest

## rest

Apply rest rules to all PCs in the session.

```
rest(session_id=1, type="short")
rest(session_id=1, type="long")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| type | str | yes | Rest type from system pack (e.g. "short", "long") |

Restores stats via formulas, resets ability uses, clears combat modifiers,
and optionally advances time. All rules come from the system pack's `rest`
section. Only affects PCs.

---

## Recall

## recall_search

Search across timeline entries and journal notes. Supports two modes:
semantic search (by meaning) and keyword search (case-insensitive text
matching).

```
recall_search(session_id=1, query="the betrayal at the temple")
recall_search(session_id=1, query="what did the elder say", source="timeline")
recall_search(session_id=1, query="player preferences", source="journal")
recall_search(session_id=1, query="dark rituals", n=10)
recall_search(session_id=1, query="dragon", mode="keyword")
recall_search(session_id=1, query="dragon", mode="keyword", source="timeline")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| query | str | yes | | Search text |
| source | str | no | "" | timeline, journal, or empty for both |
| n | int | no | 0 | Override result count. 0 = use built-in limits (timeline: 10, journal: 5) |
| mode | str | no | "semantic" | `"semantic"` for meaning-based vector search, `"keyword"` for case-insensitive text matching |

**Output (semantic mode):** table with columns `source, id, distance, content`.
Lower distance means higher relevance. Default limits apply per collection
regardless of whether `source` is specified or empty.

**Output (keyword mode):** table with columns `source, id, content, created_at`.
Ordered oldest first.

Vector collections are automatically reindexed on `session_resume`.

---

## Export

## export_dump

Export all session data to `.export/session_<id>.txt`.

```
export_dump(session_id=1)
export_dump(session_id=1, clean_previous=true)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| clean_previous | bool | no | false | Remove `.export/` directory before exporting |

**Output:**
```
EXPORTED: .export/session_1.txt
```

---

## Rules Engine

The rules engine uses a system pack (JSON definitions under `systems/`) to
compute derived stats, resolve combat actions, and manage modifiers. The
session must have a `rules_system` metadata key set (e.g. `pf2e` or `mm3e`)
so tools know which pack to load. `session_setup` sets this automatically
when you pass a system that matches a pack directory name.

## system_info

Show what a system pack provides: actions, attributes, derived stats, build
options, constraints, resolution rules, and combat positioning.

**Call this before building characters or running combat** to discover the
correct attribute names (e.g. `bonus_dodge` not `dodge_bought`) and action
names (e.g. `close_attack` not `melee_strike`).

```
system_info(system="mm3e")
system_info(session_id=1)
system_info(system="pf2e", section="actions")
system_info(system="mm3e", section="defaults")
system_info(system="mm3e", section="derived")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| system | str | no | "" | System pack name (e.g. "mm3e", "pf2e") |
| session_id | int | no | 0 | Resolve system from session's rules_system metadata |
| section | str | no | "all" | actions, defaults, derived, build, constraints, resolution, combat, or all |

At least one of `system` or `session_id` is required.

When `section="derived"`, the output includes full formulas for each stat.
When `section="all"`, formulas are omitted for brevity.

Grouping is fully data-driven — prefixes are discovered from the variable
names themselves (e.g. `bonus_*`, `ranks_*`, `prof_*`), so it works with
any system pack without hardcoded knowledge.

**Output (section="actions"):**
```
SYSTEM: Mutants & Masterminds 3e
Dice: d20

ACTIONS:
  close_attack: close_attack vs parry, range=melee
      effect: damage_rank=close_damage
  ranged_attack: ranged_attack vs dodge, range=ranged
      effect: damage_rank=ranged_damage
  grab: close_attack vs parry, range=melee
      effect: modifiers(bonus_dodge, bonus_speed)
```

**Output (section="defaults"):**
```
DEFAULTS (settable attributes):
  bonus_*: bonus_dodge, bonus_fortitude, bonus_parry, bonus_toughness, bonus_will, ...
  ranks_*: ranks_acrobatics, ranks_athletics, ranks_dodge, ranks_fortitude, ...
  adv_*: adv_close_attack, adv_defensive_roll, adv_equipment, ...
  effect_*: effect_enhanced_dodge, effect_enhanced_str, effect_protection, ...
  other: agl, awe, dex, fgt, int, pre, sta, str, damage_penalty, power_level
```

---

Derived stats are **automatically recalculated** after every state change
(character_build, character_sheet_update, combat_modifier, encounter_move,
encounter_start, encounter_end). No manual recalc call needed.

## rules_check

Roll a derived stat against a DC. Reads pre-computed values (run
`rules_calc` first).

```
rules_check(character_id=1, check="skill_athletics", dc=15)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| character_id | int | yes | | Character ID |
| check | str | yes | | Derived stat name to roll |
| dc | int | yes | | Difficulty class |
| system_path | str | no | "" | Path to system pack directory |

**Output:**
```
CHECK: Aldric — skill_athletics vs DC 15
ROLL: d20(14) + 5 = 19
RESULT: SUCCESS (by 4)
```

## rules_resolve

Resolve a combat action between two characters. Rolls attack vs defense,
then applies damage/effects per the system's resolution rules.

Two resolution strategies are supported:
- **threshold** (PF2e-style): hit if roll + attack >= defense
- **degree** (M&M3e-style): hit if roll + attack >= DC, then resistance
  check with degrees of failure

Supports single-target actions and **area effects** (via the `options`
parameter). Both characters must have derived stats computed first.

```
rules_resolve(attacker_id=1, defender_id=2, action="melee_strike")
rules_resolve(attacker_id=1, defender_id=2, action="grapple")
rules_resolve(attacker_id=1, defender_id=2, action="shove")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| attacker_id | int | yes | | Attacker character ID |
| defender_id | int | yes | | Defender character ID (0 for area self-centered) |
| action | str | yes | | Action name from system pack |
| options | str | no | "{}" | JSON object for extra options (see below) |
| system_path | str | no | "" | Path to system pack directory |

**Area effects:** Pass an `area` object inside `options`:
```
rules_resolve(attacker_id=1, defender_id=0, action="fireball", options='{"area": {"center": "self", "radius": 1, "exclude_self": true}}')
rules_resolve(attacker_id=1, defender_id=3, action="fireball", options='{"area": {"center": "target", "radius": 1}}')
```

| Area field | Type | Default | Description |
|------------|------|---------|-------------|
| center | str | "target" | Center zone: "self", "target", or a zone name |
| radius | int | 0 | Zone hops from center to include |
| exclude_self | bool | true | Exclude attacker from targets |

**Output (single target, threshold):**
```
ACTION: Aldric → Goblin
ATTACK: d20(17) + 8 = 25 vs armor_class 14
HIT!
DAMAGE: 1d8(6) + 4 = 10
current_hp: 20 → 10
```

**Output (contested action):**
```
ACTION: Aldric → Goblin
ATTACKER: d20(14) + 6 (skill_athletics) = 20
DEFENDER: d20(8) + 2 (skill_athletics) = 10
HIT! (wins by 10)
MODIFIER: grappled → bonus_speed -100 (encounter)
```

**Output (area effect):**
```
ACTION: Wizard → Goblin A
ATTACK: d20(18) + 7 = 25 vs reflex_save 12
HIT!
DAMAGE: 6d6(21) + 0 = 21
current_hp: 20 → -1
---
ACTION: Wizard → Goblin B
ATTACK: d20(9) + 7 = 16 vs reflex_save 14
HIT!
DAMAGE: 6d6(15) + 0 = 15
current_hp: 25 → 10
```

Active modifiers are visible in `encounter_status` (HUD view) and
`combat_modifier(action="list")`.

---

## Combat Modifiers

## combat_modifier

Manage transient combat modifiers on a character — pre-combat buffs,
environmental effects, spell effects, GM fiat.

```
combat_modifier(character_id=1, action="add", source="bless", target_stat="bonus_melee_attack", value=1, modifier_type="buff", bonus_type="status", duration_type="rounds", duration=10)
combat_modifier(character_id=1, action="list")
combat_modifier(character_id=1, action="remove", source="bless")
combat_modifier(character_id=1, action="clear")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| character_id | int | yes | | Character ID |
| action | str | yes | | `add`, `list`, `remove`, or `clear` |
| source | str | no | "" | Modifier source name (required for add/remove) |
| target_stat | str | no | "" | Stat to modify (required for add) |
| value | int | no | 0 | Modifier value (required for add) |
| modifier_type | str | no | "buff" | Type: buff, debuff, condition, environment |
| bonus_type | str | no | "" | Stacking group (e.g. status, circumstance, item) |
| duration_type | str | no | "encounter" | encounter, rounds, save_ends, concentration, permanent |
| duration | int | no | 0 | Duration in rounds (for rounds type) |
| save_stat | str | no | "" | Save stat for save_ends durations |
| save_dc | int | no | 0 | Save DC for save_ends durations |

**Output (add):**
```
MODIFIER ADDED: bless → bonus_melee_attack +1 [status] (rounds, 10 rounds)
```

**Output (list):**
```
MODIFIERS: character 1
  bless: bonus_melee_attack +1 [status] (rounds (10 rounds))
  zone:Corridor:cover: bonus_armor_class +2 (encounter)
```

**Output (remove):**
```
REMOVED: 1 modifier(s) from source 'bless'
```

**Output (clear):**
```
CLEARED: 3 transient modifier(s) from character 1
```

Derived stats are automatically recalculated after adding or removing
modifiers. End-of-turn modifier ticking is handled automatically by
`encounter_advance_turn`.

---

## Encounters

Zone-based combat positioning. Manages turn order, zone graph with
weighted adjacency, terrain modifiers, and movement validation.

## encounter_start

Start a combat encounter with zone-based positioning.

```
encounter_start(session_id=1, zones='[{"name":"Corridor","tags":["cover"]},{"name":"Chamber"}]', initiative='auto', placements='[{"character_id":1,"zone":"Corridor"},{"character_id":2,"zone":"Chamber"}]')
encounter_start(session_id=1, template="tavern_brawl", initiative='auto', placements='[...]')
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| zones | str | no | "[]" | JSON array of `{name, tags?}` objects. Can be empty when using template. |
| initiative | str | no | "auto" | `"auto"` or JSON array of `{character_id, roll}`. Auto rolls d20 + initiative_stat. |
| adjacency | str | no | "" | JSON array of `{from, to, weight?}` edges. Defaults to linear chain. |
| placements | str | no | "" | JSON array of `{character_id, zone}` objects |
| template | str | no | "" | Encounter template name from system pack (loads pre-built zones + adjacency) |

Zone tags are defined in the system pack's `combat.zone_tags` section.
Common tags: `difficult_terrain`, `cover`, `greater_cover`, `elevated`.
Tags can apply stat modifiers and movement cost multipliers automatically.

**Output:**
```
ENCOUNTER STARTED (session 1)
Round: 1
Initiative: Aldric (22), Goblin (15)
Zones: Corridor [cover] ↔ Chamber ↔ Balcony [elevated]
Positions: Aldric → Corridor, Goblin → Chamber
  Terrain on Aldric: cover: bonus_armor_class +2
```

## encounter_status

Return the current encounter state: round, turn, positions, distances.

```
encounter_status(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output (zone-grouped HUD):**
```
Round 1 — Turn: Aldric

Initiative: Aldric, Goblin

┌─ Corridor [cover] ───────────────────────────┐
│  Aldric (PC)  HP 35/35 ►
└────────────────────────────────────────────────┘
       ↕ 1 zone(s)
┌─ Chamber ─────────────────────────────────────┐
│  Goblin (NPC)  HP 12/20  [Rage +2 3r]
└────────────────────────────────────────────────┘
```

Shows per-character vital stats, active modifiers, and current turn marker (►).

## encounter_move

Move a character to a different zone during an encounter.

Validates movement cost against the character's movement budget (derived
stat `movement_zones` if set, otherwise unrestricted). Applies/removes
terrain modifiers automatically.

```
encounter_move(character_id=1, target_zone="Chamber")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| character_id | int | yes | Character ID |
| target_zone | str | yes | Target zone name |

**Output:**
```
MOVED: Aldric → Chamber (from Corridor, cost: 1 zone(s))
  Terrain: difficult_terrain: bonus_speed -5
```

## encounter_advance_turn

Advance to the next character in initiative order. Automatically calls
`end_turn` on the character whose turn just ended (ticks modifier durations,
removes expired modifiers). Increments the round counter when wrapping.

```
encounter_advance_turn(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output:**
```
TURN: Round 1, Goblin (character 2)
Position: Chamber
Others in zone: none
Nearest other: Aldric, 1 zone(s) in Corridor
```

## encounter_zone_update

Modify zone tags mid-combat (fire spreads, wall collapses, Darkness cast).
Updates terrain modifiers for all characters currently in the zone.

```
encounter_zone_update(session_id=1, zone_name="Corridor", tags='["difficult_terrain","cover"]')
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| zone_name | str | yes | Zone name |
| tags | str | yes | JSON array of new tags (replaces existing) |

**Output:**
```
ZONE UPDATED: Corridor
  Tags: ['cover'] → ['difficult_terrain', 'cover']
  Aldric: difficult_terrain: bonus_speed -5, cover: bonus_armor_class +2
```

## encounter_end

End the active encounter. Removes all zones, character positions, terrain
modifiers, and encounter-duration combat modifiers. Generates a combat
summary (participants, defeated, vital stats) and auto-saves it to the
journal.

```
encounter_end(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output:**
```
COMBAT ENDED (5 rounds)
Participants: Aldric (pc), Goblin (npc)
Defeated: Goblin
  Aldric: HP 28/35
Cleared: 3 terrain modifier(s), 2 combat modifier(s)
Journal saved: JOURNAL_ADDED: 42
```

---

## Templates

## ability_from_template

Create a power/ability from a common archetype template (e.g. Blast, Force
Field, Strike). Available templates depend on the system pack.

Use this instead of manually building a power with `character_sheet_update`
when the player wants a standard power archetype. The template provides
sensible defaults; overrides let you customize.

```
ability_from_template(character_id=1, template_key="Blast")
ability_from_template(character_id=1, template_key="Blast", overrides='{"ranks": 10, "extras": ["Accurate"]}')
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| character_id | int | yes | | Character ID |
| template_key | str | yes | | Template name (call with invalid key to list all) |
| overrides | str | no | "{}" | JSON object of fields to override |

**Output:**
```
ABILITY_CREATED: Blast (id=5) from template Blast
```
