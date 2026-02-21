# LoreKit -- Command Reference

This file documents every available script. Read this before running anything.

All scripts are invoked with `bash scripts/<name>.sh`. The database must be
initialized first with `init_db.sh`.

Errors print to stderr and exit with code 1. Success exits with code 0.

---

## init_db.sh

Create or verify the database. Safe to re-run.

```
bash scripts/init_db.sh
```

**Output:**
```
Database initialized at data/game.db
```

Run this once before using any other script.

---

## rolldice.sh

Roll dice using standard tabletop notation.

```
bash scripts/rolldice.sh <expression>
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
bash scripts/rolldice.sh d20         # Roll 1d20
bash scripts/rolldice.sh 3d6         # Roll 3d6
bash scripts/rolldice.sh 2d8+5       # Roll 2d8 and add 5
bash scripts/rolldice.sh 2d8-2       # Roll 2d8 and subtract 2
bash scripts/rolldice.sh d100        # Percentile roll
bash scripts/rolldice.sh 4d6kh3      # Roll 4d6, keep highest 3
```

**Output format:**
```
ROLLS: 4,3,6,2
KEPT: 6,4,3
MODIFIER: +0
TOTAL: 13
```

| Line | Meaning |
|------|---------|
| ROLLS | Every die result, comma-separated |
| KEPT | Which dice count toward the total (all of them unless kh is used) |
| MODIFIER | The flat modifier applied (+0 if none) |
| TOTAL | Final result: sum of kept dice + modifier |

---

## session.sh

Manage adventure sessions.

```
bash scripts/session.sh <action> [args]
```

### create

```
bash scripts/session.sh create --name "The Dark Forest" --setting "dark fantasy" --system "d20 fantasy"
```

All three flags are required. Output:
```
SESSION_CREATED: 1
```

### view

```
bash scripts/session.sh view 1
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
bash scripts/session.sh list
bash scripts/session.sh list --status active
bash scripts/session.sh list --status finished
```

Output: table with columns `id, name, setting, system_type, status, created_at`.

### update

```
bash scripts/session.sh update 1 --status finished
```

Output:
```
SESSION_UPDATED: 1
```

### meta-set

Store freeform key-value data on a session (house rules, world lore, etc.).
Overwrites the value if the key already exists.

```
bash scripts/session.sh meta-set 1 --key "house_rule_crits" --value "Max damage on nat 20"
```

Output:
```
META_SET: house_rule_crits
```

### meta-get

```
bash scripts/session.sh meta-get 1                          # all metadata
bash scripts/session.sh meta-get 1 --key "house_rule_crits"  # single key
```

Single key output:
```
house_rule_crits: Max damage on nat 20
```

All keys output: table with columns `key, value`.

---

## character.sh

Manage characters and their attributes, inventory, and abilities.

```
bash scripts/character.sh <action> [args]
```

### create

```
bash scripts/character.sh create --session 1 --name "Aldric" --level 3
bash scripts/character.sh create --session 1 --name "Ancião" --type npc --region 1
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
bash scripts/character.sh view 1
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
bash scripts/character.sh list --session 1
bash scripts/character.sh list --session 1 --type npc
bash scripts/character.sh list --session 1 --type npc --region 1
```

Optional filters: `--type pc|npc`, `--region <region_id>`.

Output: table with columns `id, name, type, level, status`.

### update

```
bash scripts/character.sh update 1 --level 4
bash scripts/character.sh update 1 --status dead
bash scripts/character.sh update 1 --level 5 --status alive
bash scripts/character.sh update 2 --region 1
```

Accepts `--level`, `--status`, and/or `--region`.

Output:
```
CHARACTER_UPDATED: 1
```

### set-attr

Set a character attribute. Overwrites the value if the category+key already
exists.

```
bash scripts/character.sh set-attr 1 --category stat --key strength --value 16
bash scripts/character.sh set-attr 1 --category combat --key hit_points --value 28
bash scripts/character.sh set-attr 1 --category skill --key perception --value 4
bash scripts/character.sh set-attr 1 --category save --key reflex --value 3
```

Suggested categories: `stat`, `skill`, `save`, `combat`, `resource`, `other`.
You can use any category string.

Output:
```
ATTR_SET: strength = 16
```

### get-attr

```
bash scripts/character.sh get-attr 1                    # all attributes
bash scripts/character.sh get-attr 1 --category stat    # only stats
```

All attributes output: table with columns `category, key, value`.
Filtered output: table with columns `key, value`.

### set-item

```
bash scripts/character.sh set-item 1 --name "Longsword" --desc "A fine steel blade" --qty 1 --equipped 1
```

`--name` is required. Defaults: `--desc ""`, `--qty 1`, `--equipped 0`.

Output:
```
ITEM_ADDED: 1
```

### get-items

```
bash scripts/character.sh get-items 1
```

Output: table with columns `id, name, description, quantity, equipped`.

### remove-item

```
bash scripts/character.sh remove-item 1
```

Takes the **item id** (from get-items), not the character id.

Output:
```
ITEM_REMOVED: 1
```

### set-ability

```
bash scripts/character.sh set-ability 1 --name "Fireball" --desc "3d6 fire damage in a 20ft radius" --category spell --uses "3/day"
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
bash scripts/character.sh get-abilities 1
```

Output: table with columns `id, name, category, uses, description`.

---

## region.sh

Manage regions (locations, areas) within a session.

```
bash scripts/region.sh <action> [args]
```

### create

```
bash scripts/region.sh create 1 --name "Ashar" --desc "Vila de pastores no vale"
```

`<session_id>` and `--name` are required. `--desc` defaults to empty. Output:
```
REGION_CREATED: 1
```

### list

```
bash scripts/region.sh list 1
```

Output: table with columns `id, name, description, created_at`.

### view

Shows region details and all NPCs linked to the region.

```
bash scripts/region.sh view 1
```

Output:
```
ID: 1
SESSION: 1
NAME: Ashar
DESCRIPTION: Vila de pastores no vale
CREATED: 2026-02-21T16:00:00Z

--- NPCs IN THIS REGION ---
id  name    level  status
--  ------  -----  ------
2   Ancião  1      alive
```

### update

```
bash scripts/region.sh update 1 --name "Ashar (ruínas)" --desc "A vila foi destruída"
```

Accepts `--name` and/or `--desc`. Output:
```
REGION_UPDATED: 1
```

---

## dialogue.sh

Record and query dialogues between the player and NPCs.

```
bash scripts/dialogue.sh <action> [args]
```

### add

```
bash scripts/dialogue.sh add 1 --npc 2 --speaker pc --content "Olá, ancião"
bash scripts/dialogue.sh add 1 --npc 2 --speaker "Ancião" --content "Bem-vindo, viajante"
```

`<session_id>`, `--npc`, `--speaker`, and `--content` are required. `--speaker`
should be `pc` when the player character speaks, or the NPC's name when the NPC
speaks. Output:
```
DIALOGUE_ADDED: 1
```

### list

```
bash scripts/dialogue.sh list 1 --npc 2
bash scripts/dialogue.sh list 1 --npc 2 --last 5
```

`--npc` is required. `--last <N>` limits to the most recent N lines. Output:
table with columns `id, npc, speaker, content, created_at`. Ordered oldest
first.

### search

```
bash scripts/dialogue.sh search 1 --query "viajante"
```

Searches all dialogue content in the session (case-insensitive). Output: table
with columns `id, npc, speaker, content, created_at`. Ordered oldest first.

---

## journal.sh

Append-only adventure log. Use this to record everything important that happens
during a session.

```
bash scripts/journal.sh <action> [args]
```

### add

```
bash scripts/journal.sh add 1 --type event --content "The party entered the cave"
bash scripts/journal.sh add 1 --type combat --content "Ambushed by 3 goblins"
bash scripts/journal.sh add 1 --type discovery --content "Found a hidden passage"
bash scripts/journal.sh add 1 --type npc --content "Met a merchant named Dara"
bash scripts/journal.sh add 1 --type decision --content "The party chose to spare the bandit"
bash scripts/journal.sh add 1 --type note --content "Player prefers non-combat solutions"
```

Entry types: `event`, `combat`, `discovery`, `npc`, `decision`, `note`.

Output:
```
JOURNAL_ADDED: 1
```

### list

```
bash scripts/journal.sh list 1                  # all entries (newest first)
bash scripts/journal.sh list 1 --type combat     # only combat entries
bash scripts/journal.sh list 1 --last 5          # last 5 entries
bash scripts/journal.sh list 1 --type event --last 3  # last 3 events
```

Output: table with columns `id, entry_type, content, created_at`.
Ordered newest first.

### search

```
bash scripts/journal.sh search 1 --query "dragon"
```

Searches journal content for the given text (case-insensitive).

Output: table with columns `id, entry_type, content, created_at`.
Ordered oldest first.
