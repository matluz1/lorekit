#!/usr/bin/env python3
"""time.py -- GM-controlled narrative clock."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, LoreKitError
from _args import parse_args


_VALID_UNITS = ("minutes", "hours", "days", "weeks", "months", "years")


def _get_narrative_time(db, session_id):
    """Return current narrative_time from session_meta, or empty string."""
    row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = 'narrative_time'",
        (session_id,),
    ).fetchone()
    return row[0] if row else ""


def _set_narrative_time(db, session_id, dt_str):
    """Upsert narrative_time in session_meta."""
    db.execute(
        "INSERT INTO session_meta (session_id, key, value) VALUES (?, 'narrative_time', ?) "
        "ON CONFLICT(session_id, key) DO UPDATE SET value = excluded.value",
        (session_id, dt_str),
    )
    db.commit()


def cmd_get(db, args):
    sid, _ = parse_args(args, {}, positional="session_id")
    nt = _get_narrative_time(db, int(sid))
    if not nt:
        return "NARRATIVE_TIME: (not set)"
    return f"NARRATIVE_TIME: {nt}"


def cmd_set(db, args):
    sid, p = parse_args(args, {
        "--datetime": ("datetime", True, ""),
    }, positional="session_id")
    _set_narrative_time(db, int(sid), p["datetime"])
    return f"TIME_SET: {p['datetime']}"


def cmd_advance(db, args):
    from datetime import datetime, timedelta

    sid, p = parse_args(args, {
        "--amount": ("amount", True, ""),
        "--unit": ("unit", True, ""),
    }, positional="session_id")

    session_id = int(sid)
    amount = int(p["amount"])
    unit = p["unit"]

    if unit not in _VALID_UNITS:
        raise LoreKitError(f"Invalid unit '{unit}'. Must be one of: {', '.join(_VALID_UNITS)}")
    if amount <= 0:
        raise LoreKitError("Amount must be positive")

    current = _get_narrative_time(db, session_id)
    if not current:
        raise LoreKitError("Narrative time not set. Use time_set first.")

    # Parse current time — support both with and without seconds
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(current, fmt)
            break
        except ValueError:
            continue
    else:
        raise LoreKitError(f"Cannot parse current narrative_time '{current}'. Expected ISO 8601 format.")

    # Advance
    if unit == "minutes":
        dt += timedelta(minutes=amount)
    elif unit == "hours":
        dt += timedelta(hours=amount)
    elif unit == "days":
        dt += timedelta(days=amount)
    elif unit == "weeks":
        dt += timedelta(weeks=amount)
    elif unit == "months":
        # Approximate: add 30 days per month, then adjust
        new_month = dt.month + amount
        new_year = dt.year + (new_month - 1) // 12
        new_month = ((new_month - 1) % 12) + 1
        # Clamp day to valid range for target month
        import calendar
        max_day = calendar.monthrange(new_year, new_month)[1]
        dt = dt.replace(year=new_year, month=new_month, day=min(dt.day, max_day))
    elif unit == "years":
        import calendar
        new_year = dt.year + amount
        # Handle leap year edge case (Feb 29)
        max_day = calendar.monthrange(new_year, dt.month)[1]
        dt = dt.replace(year=new_year, day=min(dt.day, max_day))

    new_time = dt.strftime("%Y-%m-%dT%H:%M")
    _set_narrative_time(db, session_id, new_time)
    return f"TIME_ADVANCED: {current} → {new_time} (+{amount} {unit})"


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python scripts/time.py <get|set|advance> [args]")
        sys.exit(1)

    action = args[0]
    args = args[1:]
    db = require_db()

    actions = {
        "get": cmd_get,
        "set": cmd_set,
        "advance": cmd_advance,
    }

    fn = actions.get(action)
    if fn is None:
        raise LoreKitError(f"Unknown action: {action}")
    print(fn(db, args))


if __name__ == "__main__":
    main()
