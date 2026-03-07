# LoreKit -- NPC Tool Reference

These are the only tools available to you. Do not attempt to use any others.

---

## roll_dice

Roll dice using standard tabletop notation.

```
roll_dice(expression="d20+3")
roll_dice(expression="2d6+5")
roll_dice(expression="4d6kh3")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| expression | str | yes | Dice expression(s), space-separated |

**Expression format:** `[N]d<sides>[kh<keep>][+/-<modifier>]`

Read the TOTAL line from the output for the result.

---

## character_view

View a full character sheet: identity, attributes, inventory, and abilities.

```
character_view(character_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| character_id | int | yes | Character ID |

Returns identity block, attributes table, inventory table, and abilities table.

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

Returns a table with columns `id, name, type, level, status`.

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

## character_get_items

List all items in a character's inventory.

```
character_get_items(character_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| character_id | int | yes | Character ID |

Returns a table with columns `id, name, description, quantity, equipped`.

## character_get_abilities

List all abilities of a character.

```
character_get_abilities(character_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| character_id | int | yes | Character ID |

Returns a table with columns `id, name, category, uses, description`.

---

## region_view

View region details, parent region, sub-regions, and NPCs in the region.

```
region_view(region_id=1)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| region_id | int | yes | Region ID |

---

## timeline_list

List timeline entries.

```
timeline_list(session_id=1, last=10)
timeline_list(session_id=1, id="42")
timeline_list(session_id=1, id="10-20")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| type | str | no | "" | narration or player_choice |
| last | int | no | 0 | Limit to last N entries |
| id | str | no | "" | Single ID `"42"` or range `"10-20"` |

Returns a table with columns `id, entry_type, content, created_at`.

## timeline_search

Search timeline content by keyword (case-insensitive).

```
timeline_search(session_id=1, query="dragon")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| query | str | yes | Search text |

---

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

## journal_search

Search journal content by keyword (case-insensitive).

```
journal_search(session_id=1, query="player prefers")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | int | yes | Session ID |
| query | str | yes | Search text |

---

## recall_search

Semantic search across timeline and journal. Finds relevant content by
meaning, not just exact keywords.

```
recall_search(session_id=1, query="the betrayal at the temple")
recall_search(session_id=1, query="what did the elder say", source="timeline")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | int | yes | | Session ID |
| query | str | yes | | Search text |
| source | str | no | "" | timeline, journal, or empty for both |
| n | int | no | 0 | Override result count (0 = defaults) |

Returns a table with columns `source, id, distance, content`. Lower distance
means higher relevance.

**Recall returns summaries, not full text.** When you need the full narration,
use the `id` from the results to fetch it:
```
recall_search(session_id=1, query="dragon attack")
# sees timeline_42 is relevant
timeline_list(session_id=1, id="42")
```
