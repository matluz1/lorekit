# LoreKit -- GM Tool Reference

This file documents every tool available to the Game Master. Read this
before using anything.

All tools are called via the LoreKit MCP server. The database must be
initialized first with `init_db`.

Errors are returned as text starting with `ERROR:`.

Tools are organized into two groups:
- **Aggregate tools** (recommended) — high-level wrappers that combine common
  multi-step workflows into single calls. Use these by default.
- **Domain tools** — individual operations organized by domain. Use these when
  you need to do something the aggregates don't cover.

---

## init_db

Create or verify the database. Safe to re-run.

```
init_db()
```

**Output:**
```
Database initialized at data/game.db
```

Run this once before using any other tool.

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

## time_set

Set the in-game narrative time to an absolute value.

```
time_set(session_id=1, datetime="1347-03-15T14:00")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| datetime | str | yes | ISO 8601 datetime (e.g. "1347-03-15T14:00") |

**Output:**
```
TIME_SET: 1347-03-15T14:00
```

## time_advance

Advance the in-game clock by a given amount.

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

Update session status.

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

## story_set

Create or overwrite the story plan for a session.

```
story_set(session_id=1, size="short", premise="A cursed forest threatens the village")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| size | str | yes | oneshot, short, or campaign |
| premise | str | yes | One-line story premise |

**Output:**
```
STORY_SET: 1
```

## story_view

Show the story premise and all acts. Optionally show full details for a
specific act.

```
story_view(session_id=1)
story_view(session_id=1, act_id=2)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| act_id | int | no | 0 | Act ID. When given, shows full details for that act instead of the overview. |

**Output (overview, act_id=0):**
```
ID: 1
SESSION: 1
SIZE: short
PREMISE: A cursed forest threatens the village
CREATED: 2026-02-21T16:00:00Z

--- ACTS ---
act_order  title          status
---------  -------------  ---------
1          The Call        active
2          The Descent     pending
3          The Resolution  pending
```

**Output (single act, act_id=2):**
```
ID: 2
SESSION: 1
ORDER: 2
TITLE: The Descent
DESCRIPTION: Heroes descend into the cursed forest
GOAL: Find the source of the curse
EVENT: The guardian awakens
STATUS: pending
CREATED: 2026-02-21T16:00:00Z
```

## story_add_act

Append an act to the story. Order is auto-assigned.

```
story_add_act(session_id=1, title="The Call", desc="Heroes are summoned", goal="Reach the temple", event="The temple collapses")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| title | str | yes | | Act title |
| desc | str | no | "" | Description |
| goal | str | no | "" | What PCs pursue |
| event | str | no | "" | Turning point |

**Output:**
```
ACT_ADDED: 1
```

## story_update_act

Update one or more fields on an act.

```
story_update_act(act_id=1, status="active")
story_update_act(act_id=1, title="New Title", desc="New description")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| act_id | int | yes | | Act ID |
| title | str | no | "" | New title |
| desc | str | no | "" | New description |
| goal | str | no | "" | New goal |
| event | str | no | "" | New event |
| status | str | no | "" | New status |

**Output:**
```
ACT_UPDATED: 1
```

## story_advance

Complete the current active act and activate the next pending one.

```
story_advance(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output (next act exists):**
```
ACT_ADVANCED: completed act 1, activated act 2
```

**Output (no more acts):**
```
ACT_ADVANCED: completed act 3, no remaining acts
```

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

## region_create

Create a region in a session.

```
region_create(session_id=1, name="Ashar", desc="A shepherds' village in the valley")
region_create(session_id=1, name="Dockside", desc="The harbor quarter", parent_id=1)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| name | str | yes | | Region name |
| desc | str | no | "" | Description |
| parent_id | int | no | 0 | Parent region ID (for nesting) |

**Output:**
```
REGION_CREATED: 1
```

## region_list

List all regions in a session.

```
region_list(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output:** table with columns `id, name, description, parent, created_at`.

## region_view

Shows region details, parent region, sub-regions, and all NPCs linked to the region.

```
region_view(region_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| region_id | int | yes | Region ID |

**Output:**
```
ID: 1
SESSION: 1
NAME: Ashar
DESCRIPTION: A shepherds' village in the valley
PARENT: Kingdom of Valen (id=3)
CREATED: 2026-02-21T16:00:00Z

--- SUB-REGIONS ---
  [4] Market Square
  [5] Temple District

--- NPCs IN THIS REGION ---
id  name    level  status
--  ------  -----  ------
2   Elder   1      alive
```

The PARENT line only appears if the region has a parent. The SUB-REGIONS section only appears if child regions exist.

## region_update

Update region name, description, and/or parent.

```
region_update(region_id=1, name="Ashar (ruins)", desc="The village was destroyed")
region_update(region_id=4, parent_id=1)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| region_id | int | yes | | Region ID |
| name | str | no | "" | New name |
| desc | str | no | "" | New description |
| parent_id | int | no | 0 | New parent region ID |

**Output:**
```
REGION_UPDATED: 1
```

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

## recall_reindex

Rebuild the vector collections from SQL data for a session. Use after
importing data or if the vector DB gets out of sync.

```
recall_reindex(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output:**
```
REINDEX_COMPLETE: 5 timeline entries, 2 journal entries
```

---

## Export

## export_dump

Export all session data to `.export/session_<id>.txt`.

```
export_dump(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output:**
```
EXPORTED: .export/session_1.txt
```

## export_clean

Remove the `.export/` directory and all files inside it.

```
export_clean()
```

**Output:**
```
CLEANED: .export
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

## rules_calc

Recompute all derived stats for a character using the rules engine.

Loads the system pack, reads the character's base attributes, resolves the
dependency graph (topological sort), writes derived stats back to the sheet,
and returns a summary of what changed.

**Run this after any attribute change** — level up, equipment swap, buff
applied, etc. — to keep derived stats (AC, attack bonus, saves, skill
modifiers) current.

```
rules_calc(character_id=1)
rules_calc(character_id=1, system_path="systems/pf2e")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| character_id | int | yes | | Character ID |
| system_path | str | no | "" | Path to system pack directory. If empty, auto-resolves from session metadata. |

**Output:**
```
RULES_CALC: Aldric
  str_mod: 0 → 3
  skill_athletics: 0 → 5
  armor_class: 0 → 16
  (12 unchanged)
```

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

## rules_modifiers

Show modifier decomposition for a character's stats. Displays all active
modifiers with their types, sources, and which ones survived stacking.

```
rules_modifiers(character_id=1)
rules_modifiers(character_id=1, stat="armor_class")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| character_id | int | yes | | Character ID |
| stat | str | no | "" | Filter to a single stat, or empty for all |
| system_path | str | no | "" | Path to system pack directory |

**Output:**
```
MODIFIERS: Aldric — armor_class
  build: bonus_armor_class +5 [item]
  zone:Corridor:cover: bonus_armor_class +2 [circumstance]
  shield_spell: bonus_armor_class +1 [item] (suppressed)
```

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

After adding or removing modifiers, run `rules_calc` to recompute derived
stats.

---

## End of Turn

## end_turn

Tick durations on a character's combat modifiers at end of turn.

Processes each modifier according to the system pack's `end_turn` config:
- **rounds**: decrement duration, remove when expired (reaches 0)
- **save_ends**: roll a save (save_stat vs save_dc), remove on success

Automatically recomputes derived stats when modifiers expire.

```
end_turn(character_id=1)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| character_id | int | yes | | Character ID |
| system_path | str | no | "" | Path to system pack directory |

**Output:**
```
END TURN: Goblin
  TICKED: bless (9 rounds remaining)
  SAVE: grappled — fortitude d20(16) + 2 = 18 vs DC 15 → SUCCESS
    REMOVED: grappled (bonus_speed -100)
  RECOMPUTED: speed: 0 → 25
```

---

## Encounters

Zone-based combat positioning. Manages turn order, zone graph with
weighted adjacency, terrain modifiers, and movement validation.

## encounter_start

Start a combat encounter with zone-based positioning.

```
encounter_start(session_id=1, zones='[{"name":"Corridor","tags":["cover"]},{"name":"Chamber"},{"name":"Balcony","tags":["elevated"]}]', initiative='[{"character_id":1,"roll":22},{"character_id":2,"roll":15}]', adjacency='[{"from":"Corridor","to":"Chamber","weight":1},{"from":"Chamber","to":"Balcony","weight":1}]', placements='[{"character_id":1,"zone":"Corridor"},{"character_id":2,"zone":"Chamber"}]')
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| zones | str | yes | | JSON array of `{name, tags?}` objects |
| initiative | str | yes | | JSON array of `{character_id, roll}` objects |
| adjacency | str | no | "" | JSON array of `{from, to, weight?}` edges. Defaults to linear chain. |
| placements | str | no | "" | JSON array of `{character_id, zone}` objects |

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

**Output:**
```
ENCOUNTER STATUS (session 1)
Round: 1, Turn: Aldric
Initiative: Aldric, Goblin
Positions:
  Aldric → Corridor [cover]
  Goblin → Chamber
Distances:
  Aldric ↔ Goblin: 1 zone(s)
```

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

Advance to the next character in initiative order. Increments the round
counter when wrapping past the last character.

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
modifiers, and encounter-duration combat modifiers.

```
encounter_end(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output:**
```
ENCOUNTER ENDED (session 1, 5 rounds). Cleared: 3 terrain modifier(s), 2 combat modifier(s).
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
