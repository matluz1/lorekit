#!/usr/bin/env python3
"""rolldice.py -- Roll dice using standard tabletop notation."""

import re
import secrets
import sys


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
        print(f"ERROR: Invalid dice expression: {expr}", file=sys.stderr)
        print("Expected format: [N]d<sides>[kh<keep>][+/-<modifier>]", file=sys.stderr)
        sys.exit(1)

    num = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))
    keep = int(m.group(4)) if m.group(4) else None
    mod_sign = m.group(5)[0] if m.group(5) else None
    mod_val = int(m.group(6)) if m.group(6) else 0

    if num < 1:
        print("ERROR: Number of dice must be at least 1", file=sys.stderr)
        sys.exit(1)

    if sides < 2:
        print("ERROR: Dice must have at least 2 sides", file=sys.stderr)
        sys.exit(1)

    if keep is not None:
        if keep < 1 or keep > num:
            print(f"ERROR: Keep count must be between 1 and {num}", file=sys.stderr)
            sys.exit(1)

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

    return {
        "rolls": ",".join(str(r) for r in rolls),
        "kept": ",".join(str(k) for k in kept),
        "modifier": modifier,
        "total": total,
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
