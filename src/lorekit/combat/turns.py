"""Turn lifecycle — end-of-turn duration ticking and start-of-turn effects."""

from __future__ import annotations

import json
import math

from cruncher.dice import roll_expr
from cruncher.system_pack import SystemPack, load_system_pack
from cruncher.types import CharacterData
from lorekit.combat.effects import _apply_degree_effect
from lorekit.combat.helpers import _get_attr_str, _get_derived, _sync_and_recalc, _write_attr
from lorekit.db import LoreKitError
from lorekit.rules import load_character_data


def end_turn(db, character_id: int, pack_dir: str) -> str:
    """Tick durations on a character's combat modifiers at end of turn.

    Reads the system pack's end_turn config, processes each active modifier
    according to its duration_type's declared tick behavior, and returns a
    summary of what changed.

    Tick behaviors:
    - decrement: subtract 1 from duration, remove at remove_at (default 0)
    - check: roll a save (save_stat vs save_dc on the modifier row),
      remove on success if remove_on="success"
    """

    pack = load_system_pack(pack_dir)
    char = load_character_data(db, character_id)

    if not pack.end_turn:
        return f"END TURN: {char.name} — no end_turn config in system pack"

    # Auto-checkpoint before ticking so turn_revert can undo
    from lorekit.support.checkpoint import create_checkpoint

    create_checkpoint(db, char.session_id)

    # Load all active combat_state rows for this character
    rows = db.execute(
        "SELECT id, source, target_stat, value, duration_type, duration, "
        "save_stat, save_dc, applied_by FROM combat_state WHERE character_id = ?",
        (character_id,),
    ).fetchall()

    if not rows:
        return f"END TURN: {char.name} — no active modifiers"

    lines = [f"END TURN: {char.name}"]
    removed_any = False

    for row_id, source, target_stat, value, dur_type, duration, save_stat, save_dc, applied_by in rows:
        tick_cfg = pack.end_turn.get(dur_type)
        if tick_cfg is None:
            continue  # duration type not configured for ticking

        action = tick_cfg.get("action")

        if action == "decrement":
            remove_at = tick_cfg.get("remove_at", 0)
            if duration is None:
                continue  # no duration set, nothing to decrement
            new_dur = duration - 1
            if new_dur <= remove_at:
                db.execute(
                    "DELETE FROM combat_state WHERE id = ?",
                    (row_id,),
                )
                lines.append(f"  EXPIRED: {source} ({target_stat} {value:+d}) — removed")
                removed_any = True
            else:
                db.execute(
                    "UPDATE combat_state SET duration = ? WHERE id = ?",
                    (new_dur, row_id),
                )
                lines.append(f"  TICKED: {source} ({new_dur} rounds remaining)")

        elif action == "check":
            remove_on = tick_cfg.get("remove_on", "success")
            if not save_stat or save_dc is None:
                lines.append(f"  SKIPPED: {source} — missing save_stat/save_dc")
                continue

            # Read the character's derived stat for the save
            derived = char.attributes.get("derived", {})
            bonus_str = derived.get(save_stat)
            if bonus_str is None:
                lines.append(f"  SKIPPED: {source} — save stat '{save_stat}' not found")
                continue

            bonus = int(bonus_str)
            result = roll_expr(pack.dice)
            roll_val = result["total"]
            total = roll_val + bonus
            success = total >= save_dc

            outcome_str = "SUCCESS" if success else "FAILURE"
            lines.append(
                f"  SAVE: {source} — {save_stat} "
                f"{pack.dice}({roll_val}) + {bonus} = {total} vs DC {save_dc} "
                f"→ {outcome_str}"
            )

            should_remove = (remove_on == "success" and success) or (remove_on == "failure" and not success)
            if should_remove:
                db.execute(
                    "DELETE FROM combat_state WHERE id = ?",
                    (row_id,),
                )
                lines.append(f"    REMOVED: {source} ({target_stat} {value:+d})")
                removed_any = True

        elif action == "escape_check":
            # Roll character's escape stat vs the source's DC stat
            escape_stat = tick_cfg.get("save_stat")
            dc_stat = tick_cfg.get("save_dc_stat")
            if not escape_stat or not dc_stat:
                lines.append(f"  SKIPPED: {source} — missing save_stat/save_dc_stat in end_turn config")
                continue

            derived = char.attributes.get("derived", {})
            bonus_str = derived.get(escape_stat)
            if bonus_str is None:
                lines.append(f"  SKIPPED: {source} — escape stat '{escape_stat}' not found")
                continue

            bonus = int(bonus_str)

            # Look up DC from the applied_by character's derived stats
            dc_val = 0
            if applied_by:
                source_char = load_character_data(db, applied_by)
                source_derived = source_char.attributes.get("derived", {})
                dc_str = source_derived.get(dc_stat)
                if dc_str is not None:
                    dc_val = int(dc_str)

            result = roll_expr(pack.dice)
            roll_val = result["total"]
            total = roll_val + bonus
            success = total >= dc_val

            outcome_str = "ESCAPED" if success else "HELD"
            lines.append(
                f"  ESCAPE: {source} — {escape_stat} "
                f"{pack.dice}({roll_val}) + {bonus} = {total} vs {dc_stat} {dc_val} "
                f"→ {outcome_str}"
            )

            if success:
                db.execute(
                    "DELETE FROM combat_state WHERE id = ?",
                    (row_id,),
                )
                lines.append(f"    FREED: {source} ({target_stat} {value:+d}) — removed")
                removed_any = True

        elif action == "modify_attribute":
            attr_key = tick_cfg.get("attribute")
            if not attr_key:
                continue
            delta = tick_cfg.get("delta", -1)
            floor_val = tick_cfg.get("floor")
            ceiling_val = tick_cfg.get("ceiling")
            try:
                current = _get_derived(char, attr_key)
            except LoreKitError:
                current = 0
            new_val = current + delta
            if floor_val is not None:
                new_val = max(int(floor_val), new_val)
            if ceiling_val is not None:
                new_val = min(int(ceiling_val), new_val)
            if new_val != current:
                _write_attr(db, character_id, attr_key, new_val)
                lines.append(f"  TICK: {source} — {attr_key}: {current} → {new_val}")
                removed_any = True  # trigger recalc

        elif action == "auto_save":
            save_stat_cfg = tick_cfg.get("save_stat")
            dc_cfg = tick_cfg.get("dc", 15)
            if not save_stat_cfg:
                lines.append(f"  SKIPPED: {source} — missing save_stat in auto_save config")
                continue

            derived = char.attributes.get("derived", {})
            bonus = int(derived.get(save_stat_cfg, 0))
            result = roll_expr(pack.dice)
            total = result["total"] + bonus
            success = total >= dc_cfg

            lines.append(
                f"  AUTO-SAVE: {source} — {save_stat_cfg} "
                f"{pack.dice}({result['total']}) + {bonus} = {total} vs DC {dc_cfg} "
                f"→ {'SUCCESS' if success else 'FAILURE'}"
            )

            outcome = tick_cfg.get("on_success", {}) if success else tick_cfg.get("on_failure", {})
            if outcome:
                _apply_degree_effect(db, char, outcome, lines)
                removed_any = True  # trigger recalc

        elif action == "worsen":
            track_attr = tick_cfg.get("attribute", f"{source}_degree")
            max_degree = tick_cfg.get("max_degree", 3)
            try:
                current = _get_derived(char, track_attr)
            except LoreKitError:
                current = 0
            if current < max_degree:
                new_val = current + 1
                _write_attr(db, character_id, track_attr, new_val)
                lines.append(f"  WORSENED: {source} — {track_attr}: {current} → {new_val}")
                removed_any = True  # trigger recalc
            else:
                lines.append(f"  WORSENED: {source} — already at max degree {max_degree}")

    db.commit()

    # Recompute derived stats if any modifiers were removed
    if removed_any:
        from lorekit.rules import rules_calc as _rules_calc

        recomp = _rules_calc(db, character_id, pack_dir)
        # Extract change lines from recompute output
        for line in recomp.split("\n"):
            if line.startswith("  ") and "→" in line:
                lines.append(f"  RECOMPUTED: {line.strip()}")

    # Sync condition modifiers (conditions may have changed after modifier expiry)
    _sync_and_recalc(db, character_id, pack, lines)

    return "\n".join(lines)


def start_turn(db, character_id: int, pack_dir: str) -> str:
    """Process start-of-turn effects on a character's combat modifiers.

    Reads the system pack's start_turn config and processes each active
    modifier whose duration_type has a declared tick behavior.

    Tick behaviors:
    - remove: delete all modifiers with this duration_type
    - warn: emit a reminder listing active modifiers of this duration_type
    """
    pack = load_system_pack(pack_dir)
    char = load_character_data(db, character_id)

    if not pack.start_turn:
        return ""

    rows = db.execute(
        "SELECT id, source, target_stat, value, duration_type, duration, metadata "
        "FROM combat_state WHERE character_id = ?",
        (character_id,),
    ).fetchall()

    if not rows:
        return ""

    lines: list[str] = [f"START TURN: {char.name}"]
    removed_any = False
    has_output = False

    # Collect warnings by duration_type
    warn_items: dict[str, list[str]] = {}

    for row_id, source, target_stat, value, dur_type, duration, metadata in rows:
        tick_cfg = pack.start_turn.get(dur_type)
        if tick_cfg is None:
            continue

        action = tick_cfg.get("action")

        if action == "remove":
            db.execute("DELETE FROM combat_state WHERE id = ?", (row_id,))
            lines.append(f"  EXPIRED: {source} ({target_stat} {value:+d}) — removed")
            removed_any = True
            has_output = True

        elif action == "warn":
            warn_items.setdefault(dur_type, []).append(f"{source} ({target_stat} {value:+d})")

        elif action == "replenish":
            # Reset reaction uses (e.g. reaction duration back to 1)
            reset_to = tick_cfg.get("reset_to", 1)
            if duration < reset_to:
                db.execute(
                    "UPDATE combat_state SET duration = ? WHERE id = ?",
                    (reset_to, row_id),
                )
                lines.append(f"  REPLENISHED: {source} (reaction ready)")
                has_output = True

        elif action == "retry_action":
            # Homing: retry a deferred attack
            try:
                meta = json.loads(metadata) if metadata else None
            except (ValueError, TypeError):
                meta = None
            if not meta:
                continue

            retry_action = meta.get("action")
            retry_target = meta.get("target_id")
            retries_left = meta.get("retries_left", 1)

            if retry_action and retry_target:
                lines.append(f"  HOMING RETRY: {source} → re-attacking")
                try:
                    from lorekit.combat.resolve import resolve_action

                    result = resolve_action(
                        db,
                        character_id,
                        retry_target,
                        retry_action,
                        pack_dir,
                        options={"free_action": True},
                    )
                    lines.append(f"    {result}")
                    hit_retry = "HIT" in result
                except LoreKitError as e:
                    lines.append(f"    RETRY FAILED: {e}")
                    hit_retry = False

                if hit_retry or retries_left <= 1:
                    db.execute("DELETE FROM combat_state WHERE id = ?", (row_id,))
                    removed_any = True
                else:
                    meta["retries_left"] = retries_left - 1
                    db.execute(
                        "UPDATE combat_state SET metadata = ? WHERE id = ?",
                        (json.dumps(meta), row_id),
                    )
                has_output = True

    # Emit sustain warnings
    for dur_type, items in warn_items.items():
        lines.append(f"  SUSTAINED: {', '.join(items)} — free action required to maintain each")
        has_output = True

    db.commit()

    if removed_any:
        from lorekit.rules import rules_calc as _rules_calc

        recomp = _rules_calc(db, character_id, pack_dir)
        for line in recomp.split("\n"):
            if line.startswith("  ") and "→" in line:
                lines.append(f"  RECOMPUTED: {line.strip()}")

        _sync_and_recalc(db, character_id, pack, lines)

    return "\n".join(lines) if has_output else ""
