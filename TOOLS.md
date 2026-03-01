# LoreKit -- Command Reference

This file documents every available script. Read this before running anything.

All scripts are invoked with `.venv/bin/python ./scripts/<name>.py`. The database
must be initialized first with `init_db.py`.

Errors print to stderr and exit with code 1. Success exits with code 0.

---

## init_db.py

Create or verify the database. Safe to re-run.

```
.venv/bin/python ./scripts/init_db.py
```

**Output:**
```
Database initialized at data/game.db
```

Run this once before using any other script.

---

## rolldice.py

Roll dice using standard tabletop notation. Accepts one or more expressions.

```
.venv/bin/python ./scripts/rolldice.py <expression> [expression ...]
```

**Expression format:** `[N]d<sides>[kh<keep>][+/-<modifier>]`

| Part | Meaning | Required | Example |
|------|---------|----------|---------|
| N | Number of dice (default 1) | No | `3` in `3d6` |
| d\<sides\> | Die type | Yes | `d20`, `d6`, `d100` |
| kh\<keep\> | Keep highest N dice | No | `kh3` in `4d6kh3` |
| +/-\<mod\> | Add/subtract a flat number | No | `+5` in `2d8+5` |

**Examples:**
```
.venv/bin/python ./scripts/rolldice.py d20         # Roll 1d20
.venv/bin/python ./scripts/rolldice.py 3d6         # Roll 3d6
.venv/bin/python ./scripts/rolldice.py 2d8+5       # Roll 2d8 and add 5
.venv/bin/python ./scripts/rolldice.py 2d8-2       # Roll 2d8 and subtract 2
.venv/bin/python ./scripts/rolldice.py d100        # Percentile roll
.venv/bin/python ./scripts/rolldice.py 4d6kh3      # Roll 4d6, keep highest 3
.venv/bin/python ./scripts/rolldice.py d20 2d6+3 4d6kh3  # Multiple expressions
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

## session.py

Manage adventure sessions.

```
.venv/bin/python ./scripts/session.py <action> [args]
```

### create

```
.venv/bin/python ./scripts/session.py create --name "The Dark Forest" --setting "dark fantasy" --system "d20 fantasy"
```

All three flags are required. Output:
```
SESSION_CREATED: 1
```

### view

```
.venv/bin/python ./scripts/session.py view 1
```

Output:
```
ID: 1
NAME: The Dark Forest
SETTING: dark fantasy
SYSTEM: d20 fantasy
STATUS: active
CREATED: 2026-02-21T16:00:00Z
UPDATED: 2026-02-21T16:00:00Z
```

### list

```
.venv/bin/python ./scripts/session.py list
.venv/bin/python ./scripts/session.py list --status active
.venv/bin/python ./scripts/session.py list --status finished
```

Output: table with columns `id, name, setting, system_type, status, created_at`.

### update

```
.venv/bin/python ./scripts/session.py update 1 --status finished
```

Output:
```
SESSION_UPDATED: 1
```

### meta-set

Store freeform key-value data on a session (house rules, world lore, etc.).
Overwrites the value if the key already exists.

```
.venv/bin/python ./scripts/session.py meta-set 1 --key "house_rule_crits" --value "Max damage on nat 20"
```

Output:
```
META_SET: house_rule_crits
```

### meta-get

```
.venv/bin/python ./scripts/session.py meta-get 1                          # all metadata
.venv/bin/python ./scripts/session.py meta-get 1 --key "house_rule_crits"  # single key
```

Single key output:
```
house_rule_crits: Max damage on nat 20
```

All keys output: table with columns `key, value`.

---

## story.py

Manage story arcs and act-based pacing within a session.

```
.venv/bin/python ./scripts/story.py <action> [args]
```

### set

Create or overwrite the story plan for a session.

```
.venv/bin/python ./scripts/story.py set 1 --size "short" --premise "A cursed forest threatens the village"
```

Both `--size` and `--premise` are required. Size values: `oneshot`, `short`, `campaign`.
If a story already exists for the session, it is overwritten.

Output:
```
STORY_SET: 1
```

### view

Show the story premise and all acts.

```
.venv/bin/python ./scripts/story.py view 1
```

Output:
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

### add-act

Append an act to the story. Order is auto-assigned.

```
.venv/bin/python ./scripts/story.py add-act 1 --title "The Call" --desc "Heroes are summoned" --goal "Reach the temple" --event "The temple collapses"
```

`--title` is required. `--desc`, `--goal`, and `--event` default to empty.

Output:
```
ACT_ADDED: 1
```

### view-act

Show full details for a single act.

```
.venv/bin/python ./scripts/story.py view-act 1
```

Output:
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

### update-act

Update one or more fields on an act.

```
.venv/bin/python ./scripts/story.py update-act 1 --status active
.venv/bin/python ./scripts/story.py update-act 1 --title "New Title" --desc "New description"
.venv/bin/python ./scripts/story.py update-act 1 --goal "New goal" --event "New event"
```

Accepts `--title`, `--desc`, `--goal`, `--event`, and/or `--status`.

Output:
```
ACT_UPDATED: 1
```

### advance

Complete the current active act and activate the next pending one.

```
.venv/bin/python ./scripts/story.py advance 1
```

Output (next act exists):
```
ACT_ADVANCED: completed act 1, activated act 2
```

Output (no more acts):
```
ACT_ADVANCED: completed act 3, no remaining acts
```

---

## character.py

Manage characters and their attributes, inventory, and abilities.

```
.venv/bin/python ./scripts/character.py <action> [args]
```

### create

```
.venv/bin/python ./scripts/character.py create --session 1 --name "Aldric" --level 3
.venv/bin/python ./scripts/character.py create --session 1 --name "Elder" --type npc --region 1
```

`--session` and `--name` are required. `--level` defaults to 1. `--type`
defaults to `pc` (accepts `pc` or `npc`). `--region` is optional and links the
character to a region. Output:
```
CHARACTER_CREATED: 1
```

### view

Shows the full character sheet: identity, attributes, inventory, and abilities.

```
.venv/bin/python ./scripts/character.py view 1
```

Output:
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

### list

```
.venv/bin/python ./scripts/character.py list --session 1
.venv/bin/python ./scripts/character.py list --session 1 --type npc
.venv/bin/python ./scripts/character.py list --session 1 --type npc --region 1
```

Optional filters: `--type pc|npc`, `--region <region_id>`.

Output: table with columns `id, name, type, level, status`.

### update

```
.venv/bin/python ./scripts/character.py update 1 --name "Ren"
.venv/bin/python ./scripts/character.py update 1 --level 4
.venv/bin/python ./scripts/character.py update 1 --status dead
.venv/bin/python ./scripts/character.py update 1 --level 5 --status alive
.venv/bin/python ./scripts/character.py update 2 --region 1
```

Accepts `--name`, `--level`, `--status`, and/or `--region`.

Output:
```
CHARACTER_UPDATED: 1
```

### set-attr

Set a character attribute. Overwrites the value if the category+key already
exists.

```
.venv/bin/python ./scripts/character.py set-attr 1 --category stat --key strength --value 16
.venv/bin/python ./scripts/character.py set-attr 1 --category combat --key hit_points --value 28
.venv/bin/python ./scripts/character.py set-attr 1 --category skill --key perception --value 4
.venv/bin/python ./scripts/character.py set-attr 1 --category save --key reflex --value 3
```

Suggested categories: `stat`, `skill`, `save`, `combat`, `resource`, `other`.
You can use any category string.

Output:
```
ATTR_SET: strength = 16
```

### get-attr

```
.venv/bin/python ./scripts/character.py get-attr 1                    # all attributes
.venv/bin/python ./scripts/character.py get-attr 1 --category stat    # only stats
```

All attributes output: table with columns `category, key, value`.
Filtered output: table with columns `key, value`.

### set-item

```
.venv/bin/python ./scripts/character.py set-item 1 --name "Longsword" --desc "A fine steel blade" --qty 1 --equipped 1
```

`--name` is required. Defaults: `--desc ""`, `--qty 1`, `--equipped 0`.

Output:
```
ITEM_ADDED: 1
```

### get-items

```
.venv/bin/python ./scripts/character.py get-items 1
```

Output: table with columns `id, name, description, quantity, equipped`.

### remove-item

```
.venv/bin/python ./scripts/character.py remove-item 1
```

Takes the **item id** (from get-items), not the character id.

Output:
```
ITEM_REMOVED: 1
```

### set-ability

```
.venv/bin/python ./scripts/character.py set-ability 1 --name "Fireball" --desc "3d6 fire damage in a 20ft radius" --category spell --uses "3/day"
```

`--name`, `--desc`, and `--category` are required. `--uses` defaults to `at_will`.

Suggested categories: `spell`, `feat`, `power`, `trait`.
Suggested uses values: `at_will`, `1/rest`, `3/day`, `1/day`.

Output:
```
ABILITY_ADDED: 1
```

### get-abilities

```
.venv/bin/python ./scripts/character.py get-abilities 1
```

Output: table with columns `id, name, category, uses, description`.

---

## region.py

Manage regions (locations, areas) within a session.

```
.venv/bin/python ./scripts/region.py <action> [args]
```

### create

```
.venv/bin/python ./scripts/region.py create 1 --name "Ashar" --desc "A shepherds' village in the valley"
```

`<session_id>` and `--name` are required. `--desc` defaults to empty. Output:
```
REGION_CREATED: 1
```

### list

```
.venv/bin/python ./scripts/region.py list 1
```

Output: table with columns `id, name, description, created_at`.

### view

Shows region details and all NPCs linked to the region.

```
.venv/bin/python ./scripts/region.py view 1
```

Output:
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

### update

```
.venv/bin/python ./scripts/region.py update 1 --name "Ashar (ruins)" --desc "The village was destroyed"
```

Accepts `--name` and/or `--desc`. Output:
```
REGION_UPDATED: 1
```

---

## timeline.py

Unified timeline of narration and player choices. Records everything that
happens in the game in chronological order. Narration entries store the
complete text exactly as shown to the player. Player choice entries store
the player's response.

```
.venv/bin/python ./scripts/timeline.py <action> [args]
```

### add

```
.venv/bin/python ./scripts/timeline.py add 1 --type narration --content "<exact text shown to the player>"
.venv/bin/python ./scripts/timeline.py add 1 --type player_choice --content "<what the player chose or said>"
```

Entry types: `narration`, `player_choice`.

- `narration`: the complete GM text exactly as displayed to the player.
- `player_choice`: the player's response or action.

Output:
```
TIMELINE_ADDED: 1
```

### list

```
.venv/bin/python ./scripts/timeline.py list 1                              # all entries
.venv/bin/python ./scripts/timeline.py list 1 --type narration              # only narration
.venv/bin/python ./scripts/timeline.py list 1 --type player_choice          # only player choices
.venv/bin/python ./scripts/timeline.py list 1 --last 10                     # last 10 entries
```

Output: table with columns `id, entry_type, content, created_at`.
Ordered oldest first.

### search

```
.venv/bin/python ./scripts/timeline.py search 1 --query "dragon"
```

Searches timeline content for the given text (case-insensitive).

Output: table with columns `id, entry_type, content, created_at`.
Ordered oldest first.

---

## journal.py

Optional notepad for GM notes. Use this for out-of-game annotations,
player preferences, and reminders -- not for in-game events (use `timeline.py`
for those).

```
.venv/bin/python ./scripts/journal.py <action> [args]
```

### add

```
.venv/bin/python ./scripts/journal.py add 1 --type note --content "Player prefers non-combat solutions"
.venv/bin/python ./scripts/journal.py add 1 --type note --content "Remember to introduce the merchant next session"
```

Entry types: `event`, `combat`, `discovery`, `npc`, `decision`, `note`.

Output:
```
JOURNAL_ADDED: 1
```

### list

```
.venv/bin/python ./scripts/journal.py list 1                  # all entries (newest first)
.venv/bin/python ./scripts/journal.py list 1 --type note       # only notes
.venv/bin/python ./scripts/journal.py list 1 --last 5          # last 5 entries
```

Output: table with columns `id, entry_type, content, created_at`.
Ordered newest first.

### search

```
.venv/bin/python ./scripts/journal.py search 1 --query "player prefers"
```

Searches journal content for the given text (case-insensitive).

Output: table with columns `id, entry_type, content, created_at`.
Ordered oldest first.

---

## export.py

Export session data for narrative rewriting. Consolidates all session data into
a single structured text dump optimised for LLM consumption.

```
.venv/bin/python ./scripts/export.py <action> [args]
```

### dump

```
.venv/bin/python ./scripts/export.py dump 1
```

Exports all session data to `.export/session_<id>.txt`. The `.export/`
directory is created automatically and is gitignored.

Outputs all data in order: session info, story/acts, characters (with
attributes, inventory, abilities), regions, timeline, and journal.

```
EXPORTED: .export/session_1.txt
```

### clean

```
.venv/bin/python ./scripts/export.py clean
```

Removes the `.export/` directory and all files inside it.

```
CLEANED: .export
```

---

## recall.py

Semantic search across timeline entries and journal notes. Finds relevant content
by meaning, not just exact keywords. Requires `chromadb` to be installed.

```
.venv/bin/python ./scripts/recall.py <action> [args]
```

### search

```
.venv/bin/python ./scripts/recall.py search 1 --query "the betrayal at the temple"
.venv/bin/python ./scripts/recall.py search 1 --query "what did the elder say" --source timeline
.venv/bin/python ./scripts/recall.py search 1 --query "player preferences" --source journal
.venv/bin/python ./scripts/recall.py search 1 --query "dark rituals" --n 10
```

`<session_id>` and `--query` are required. `--source timeline|journal` limits
the search to one collection (default: both). `--n <N>` controls the number of
results (default: 5).

Output: table with columns `source, id, distance, content`. Lower distance
means higher relevance.

### reindex

```
.venv/bin/python ./scripts/recall.py reindex 1
```

Rebuilds the vector collections from SQL data for the given session. Use this
after importing data or if the vector DB gets out of sync.

Output:
```
REINDEX_COMPLETE: 5 timeline entries, 2 journal entries
```
