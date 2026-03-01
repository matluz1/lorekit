# LoreKit -- Tool Reference

This file documents every available tool. Read this before using anything.

All tools are called via the LoreKit MCP server. The database must be
initialized first with `init_db`.

Errors are returned as text starting with `ERROR:`.

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

## session_create

Create a new adventure session.

```
session_create(name="<name>", setting="<setting>", system="<system>")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | str | yes | Adventure name |
| setting | str | yes | World setting |
| system | str | yes | Rule system archetype |

**Output:**
```
SESSION_CREATED: 1
```

## session_view

View session details.

```
session_view(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output:**
```
ID: 1
NAME: The Dark Forest
SETTING: dark fantasy
SYSTEM: d20 fantasy
STATUS: active
CREATED: 2026-02-21T16:00:00Z
UPDATED: 2026-02-21T16:00:00Z
```

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

Show the story premise and all acts.

```
story_view(session_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |

**Output:**
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

## story_view_act

Show full details for a single act.

```
story_view_act(act_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| act_id | int | yes | Act ID |

**Output:**
```
ID: 1
SESSION: 1
ORDER: 1
TITLE: The Call
DESCRIPTION: Heroes are summoned
GOAL: Reach the temple
EVENT: The temple collapses
STATUS: pending
CREATED: 2026-02-21T16:00:00Z
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

## character_create

Create a character.

```
character_create(session=1, name="Aldric", level=3)
character_create(session=1, name="Elder", level=1, type="npc", region=1)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session | int | yes | | Session ID |
| name | str | yes | | Character name |
| level | int | yes | | Character level |
| type | str | no | "pc" | pc or npc |
| region | int | no | 0 | Region ID (0 = none) |

**Output:**
```
CHARACTER_CREATED: 1
```

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

## character_update

Update character fields. Only provided fields are changed.

```
character_update(character_id=1, name="Ren")
character_update(character_id=1, level=4)
character_update(character_id=1, status="dead")
character_update(character_id=2, region=1)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| character_id | int | yes | | Character ID |
| name | str | no | "" | New name |
| level | int | no | 0 | New level |
| status | str | no | "" | New status |
| region | int | no | 0 | New region ID |

**Output:**
```
CHARACTER_UPDATED: 1
```

## character_set_attr

Set a character attribute. Overwrites the value if the category+key already
exists.

```
character_set_attr(character_id=1, category="stat", key="strength", value="16")
character_set_attr(character_id=1, category="combat", key="hit_points", value="28")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| character_id | int | yes | Character ID |
| category | str | yes | e.g. stat, skill, save, combat, resource |
| key | str | yes | Attribute name |
| value | str | yes | Attribute value |

**Output:**
```
ATTR_SET: strength = 16
```

## character_get_attr

Get character attributes. Optionally filter by category.

```
character_get_attr(character_id=1)
character_get_attr(character_id=1, category="stat")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| character_id | int | yes | | Character ID |
| category | str | no | "" | Filter by category |

All attributes output: table with columns `category, key, value`.
Filtered output: table with columns `key, value`.

## character_set_item

Add an item to a character's inventory.

```
character_set_item(character_id=1, name="Longsword", desc="A fine steel blade", qty=1, equipped=1)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| character_id | int | yes | | Character ID |
| name | str | yes | | Item name |
| desc | str | no | "" | Description |
| qty | int | no | 1 | Quantity |
| equipped | int | no | 0 | 1 = equipped, 0 = not |

**Output:**
```
ITEM_ADDED: 1
```

## character_get_items

List all items in a character's inventory.

```
character_get_items(character_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| character_id | int | yes | Character ID |

**Output:** table with columns `id, name, description, quantity, equipped`.

## character_remove_item

Remove an item from inventory by item ID (from `character_get_items`).

```
character_remove_item(item_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| item_id | int | yes | Item ID |

**Output:**
```
ITEM_REMOVED: 1
```

## character_set_ability

Add an ability to a character.

```
character_set_ability(character_id=1, name="Fireball", desc="3d6 fire damage in a 20ft radius", category="spell", uses="3/day")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| character_id | int | yes | | Character ID |
| name | str | yes | | Ability name |
| desc | str | yes | | What it does |
| category | str | yes | | spell, feat, power, trait |
| uses | str | no | "at_will" | at_will, 1/rest, 3/day, 1/day |

**Output:**
```
ABILITY_ADDED: 1
```

## character_get_abilities

List all abilities of a character.

```
character_get_abilities(character_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| character_id | int | yes | Character ID |

**Output:** table with columns `id, name, category, uses, description`.

---

## region_create

Create a region in a session.

```
region_create(session_id=1, name="Ashar", desc="A shepherds' village in the valley")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| name | str | yes | | Region name |
| desc | str | no | "" | Description |

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

**Output:** table with columns `id, name, description, created_at`.

## region_view

Shows region details and all NPCs linked to the region.

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
CREATED: 2026-02-21T16:00:00Z

--- NPCs IN THIS REGION ---
id  name    level  status
--  ------  -----  ------
2   Elder   1      alive
```

## region_update

Update region name and/or description.

```
region_update(region_id=1, name="Ashar (ruins)", desc="The village was destroyed")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| region_id | int | yes | | Region ID |
| name | str | no | "" | New name |
| desc | str | no | "" | New description |

**Output:**
```
REGION_UPDATED: 1
```

---

## timeline_add

Add a timeline entry. Records narration and player choices in chronological
order. Narration entries should include a `summary` for semantic search
indexing.

```
timeline_add(session_id=1, type="narration", content="<exact text shown to the player>", summary="<1-2 sentence summary>")
timeline_add(session_id=1, type="player_choice", content="<what the player chose or said>")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| type | str | yes | | narration or player_choice |
| content | str | yes | | Entry text |
| summary | str | no | "" | 1-2 sentence summary for semantic search (narration only) |

**Output:**
```
TIMELINE_ADDED: 1
```

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

## timeline_search

Search timeline content by keyword (case-insensitive).

```
timeline_search(session_id=1, query="dragon")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| query | str | yes | Search text |

**Output:** table with columns `id, entry_type, content, created_at`.
Ordered oldest first.

---

## journal_add

Add a journal entry. Use for GM notes, not in-game events.

```
journal_add(session_id=1, type="note", content="Player prefers non-combat solutions")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| type | str | yes | event, combat, discovery, npc, decision, note |
| content | str | yes | Entry text |

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

## journal_search

Search journal content by keyword (case-insensitive).

```
journal_search(session_id=1, query="player prefers")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| query | str | yes | Search text |

**Output:** table with columns `id, entry_type, content, created_at`.
Ordered oldest first.

---

## recall_search

Semantic search across timeline entries and journal notes. Finds relevant
content by meaning, not just exact keywords.

```
recall_search(session_id=1, query="the betrayal at the temple")
recall_search(session_id=1, query="what did the elder say", source="timeline")
recall_search(session_id=1, query="player preferences", source="journal")
recall_search(session_id=1, query="dark rituals", n=10)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| query | str | yes | | Search text |
| source | str | no | "" | timeline, journal, or empty for both |
| n | int | no | 0 | Override result count. 0 = use built-in limits (timeline: 10, journal: 5) |

**Output:** table with columns `source, id, distance, content`. Lower distance
means higher relevance. Default limits apply per collection regardless of
whether `source` is specified or empty.

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
