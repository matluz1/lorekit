#!/usr/bin/env python3
"""rolldice.py -- Roll dice using standard tabletop notation."""

import re
import secrets
import sys

from _db import LoreKitError


def usage():
    name = "rolldice.py"
    print(f"Usage: {name} <expression> [expression ...]")
    print()
    print("Examples:")
    print(f"  {name} d20        # Roll 1d20")
    print(f"  {name} 3d6        # Roll 3d6")
    print(f"  {name} 2d8+5      # Roll 2d8 and add 5")
    print(f"  {name} 4d6kh3     # Roll 4d6, keep highest 3")
    print(f"  {name} d20 2d6+3  # Roll multiple expressions")
    sys.exit(1)


def roll_expr(expr: str) -> dict:
    """Parse and roll a single dice expression. Returns structured result."""
    expr = expr.lower()

    m = re.fullmatch(r"([0-9]*)d([0-9]+)(kh([0-9]+))?([+-]([0-9]+))?", expr)
    if not m:
        raise LoreKitError(f"Invalid dice expression: {expr}\nExpected format: [N]d<sides>[kh<keep>][+/-<modifier>]")

    num = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))
    keep = int(m.group(4)) if m.group(4) else None
    mod_sign = m.group(5)[0] if m.group(5) else None
    mod_val = int(m.group(6)) if m.group(6) else 0

    if num < 1:
        raise LoreKitError("Number of dice must be at least 1")

    if sides < 2:
        raise LoreKitError("Dice must have at least 2 sides")

    if keep is not None:
        if keep < 1 or keep > num:
            raise LoreKitError(f"Keep count must be between 1 and {num}")

    rolls = [secrets.randbelow(sides) + 1 for _ in range(num)]

    if keep is not None:
        kept = sorted(rolls, reverse=True)[:keep]
    else:
        kept = list(rolls)

    total = sum(kept)

    modifier = "+0"
    if mod_val != 0:
        if mod_sign == "-":
            modifier = f"-{mod_val}"
            total -= mod_val
        else:
            modifier = f"+{mod_val}"
            total += mod_val

    # For single-die rolls (no keep filter), expose the raw die result
    # so callers can detect natural 20s, natural 1s, etc.
    natural = rolls[0] if num == 1 and keep is None else None

    return {
        "rolls": ",".join(str(r) for r in rolls),
        "kept": ",".join(str(k) for k in kept),
        "modifier": modifier,
        "total": total,
        "natural": natural,
    }


def format_result(result: dict) -> str:
    """Format a roll result as output lines."""
    lines = [
        f"ROLLS: {result['rolls']}",
        f"KEPT: {result['kept']}",
        f"MODIFIER: {result['modifier']}",
        f"TOTAL: {result['total']}",
    ]
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        usage()

    expressions = sys.argv[1:]

    if len(expressions) == 1:
        result = roll_expr(expressions[0])
        print(format_result(result))
    else:
        blocks = []
        for expr in expressions:
            result = roll_expr(expr)
            block = f"--- {expr} ---\n{format_result(result)}"
            blocks.append(block)
        print("\n\n".join(blocks))


if __name__ == "__main__":
    main()
