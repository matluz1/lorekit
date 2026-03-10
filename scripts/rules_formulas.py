"""Minimal expression evaluator for Crunch rule formulas.

Supports arithmetic, function calls (floor, ceil, max, min, abs, sum, per,
ratio, table, if), variable lookups (including dotted paths), and comparison
operators.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------

@dataclass
class Num:
    value: float | int | bool

@dataclass
class Str:
    value: str

@dataclass
class Var:
    parts: list[str]   # ["armor", "bonus"] for dotted access

@dataclass
class BinOp:
    op: str
    left: Any
    right: Any

@dataclass
class UnaryNeg:
    operand: Any

@dataclass
class Compare:
    op: str
    left: Any
    right: Any

@dataclass
class Call:
    name: str
    args: list


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"""
    (?P<num>    \d+(?:\.\d+)? ) |
    (?P<cmp>    [<>!=]=|[<>]  ) |
    (?P<ident>  [a-zA-Z_][a-zA-Z0-9_]* ) |
    (?P<str>    '[^']*'|"[^"]*" ) |
    (?P<op>     [+\-*/(),.]   ) |
    (?P<ws>     \s+           )
""", re.VERBOSE)

_KEYWORDS = {"true": True, "false": False}


def _tokenize(expr: str) -> list[tuple[str, Any]]:
    tokens: list[tuple[str, Any]] = []
    for m in _TOKEN_RE.finditer(expr):
        if m.group("ws"):
            continue
        elif m.group("num"):
            raw = m.group("num")
            tokens.append(("NUM", float(raw) if "." in raw else int(raw)))
        elif m.group("cmp"):
            tokens.append(("CMP", m.group("cmp")))
        elif m.group("ident"):
            word = m.group("ident")
            if word in _KEYWORDS:
                tokens.append(("NUM", _KEYWORDS[word]))
            else:
                tokens.append(("IDENT", word))
        elif m.group("str"):
            tokens.append(("STR", m.group("str")[1:-1]))
        elif m.group("op"):
            tokens.append((m.group("op"), m.group("op")))
    tokens.append(("EOF", None))
    return tokens


# ---------------------------------------------------------------------------
# Parser — recursive descent, produces AST
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, tokens: list[tuple[str, Any]]):
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> tuple[str, Any]:
        return self.tokens[self.pos]

    def _advance(self) -> tuple[str, Any]:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, typ: str) -> Any:
        tok = self._advance()
        if tok[0] != typ:
            raise ValueError(f"Expected {typ}, got {tok}")
        return tok[1]

    def parse(self):
        node = self._expr()
        if self._peek()[0] != "EOF":
            raise ValueError(f"Unexpected token after expression: {self._peek()}")
        return node

    def _expr(self):
        return self._comparison()

    def _comparison(self):
        left = self._addition()
        if self._peek()[0] == "CMP":
            op = self._advance()[1]
            right = self._addition()
            return Compare(op, left, right)
        return left

    def _addition(self):
        left = self._term()
        while self._peek()[1] in ("+", "-"):
            op = self._advance()[1]
            right = self._term()
            left = BinOp(op, left, right)
        return left

    def _term(self):
        left = self._unary()
        while self._peek()[1] in ("*", "/"):
            op = self._advance()[1]
            right = self._unary()
            left = BinOp(op, left, right)
        return left

    def _unary(self):
        if self._peek()[1] == "-":
            self._advance()
            return UnaryNeg(self._unary())
        return self._call()

    def _call(self):
        if self._peek()[0] == "IDENT":
            # Peek ahead for function call
            if self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1][1] == "(":
                name = self._advance()[1]
                self._expect("(")
                args = []
                if self._peek()[1] != ")":
                    args.append(self._expr())
                    while self._peek()[1] == ",":
                        self._advance()
                        args.append(self._expr())
                self._expect(")")
                return Call(name, args)
        return self._atom()

    def _atom(self):
        tok = self._peek()
        if tok[0] == "NUM":
            self._advance()
            return Num(tok[1])
        if tok[0] == "STR":
            self._advance()
            return Str(tok[1])
        if tok[0] == "IDENT":
            parts = [self._advance()[1]]
            while self._peek()[1] == ".":
                self._advance()  # skip dot
                parts.append(self._expect("IDENT"))
            return Var(parts)
        if tok[1] == "(":
            self._advance()
            node = self._expr()
            self._expect(")")
            return node
        raise ValueError(f"Unexpected token: {tok}")


def parse(expr: str):
    """Parse a formula string into an AST."""
    return _Parser(_tokenize(expr)).parse()


# ---------------------------------------------------------------------------
# Dependency extraction — collect variable names referenced by a formula
# ---------------------------------------------------------------------------

def extract_deps(node) -> set[str]:
    """Return the set of variable names (top-level) referenced in the AST.

    Special handling:
    - table(name, idx): only the index expression is a dependency
    """
    if isinstance(node, (Num, Str)):
        return set()
    if isinstance(node, Var):
        return {node.parts[0]}
    if isinstance(node, BinOp):
        return extract_deps(node.left) | extract_deps(node.right)
    if isinstance(node, UnaryNeg):
        return extract_deps(node.operand)
    if isinstance(node, Compare):
        return extract_deps(node.left) | extract_deps(node.right)
    if isinstance(node, Call):
        if node.name == "table":
            # table(table_name, index) — only index deps
            deps: set[str] = set()
            for arg in node.args[1:]:
                deps |= extract_deps(arg)
            return deps
        # Generic function: all args are deps
        deps = set()
        for arg in node.args:
            deps |= extract_deps(arg)
        return deps
    return set()


# ---------------------------------------------------------------------------
# Evaluation context
# ---------------------------------------------------------------------------

@dataclass
class FormulaContext:
    """Holds all data needed to evaluate formulas."""
    values: dict[str, Any] = field(default_factory=dict)
    tables: dict[str, list] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class FormulaError(Exception):
    """Raised when formula evaluation fails."""


def evaluate(node, ctx: FormulaContext) -> Any:
    """Evaluate an AST node against a FormulaContext."""
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Str):
        return node.value
    if isinstance(node, Var):
        key = ".".join(node.parts)
        if key in ctx.values:
            return ctx.values[key]
        # Try just the first part
        if len(node.parts) == 1 and node.parts[0] in ctx.values:
            return ctx.values[node.parts[0]]
        raise FormulaError(f"Unknown variable: {key}")
    if isinstance(node, UnaryNeg):
        return -evaluate(node.operand, ctx)
    if isinstance(node, BinOp):
        left = evaluate(node.left, ctx)
        right = evaluate(node.right, ctx)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            if right == 0:
                raise FormulaError("Division by zero")
            return left / right
    if isinstance(node, Compare):
        left = evaluate(node.left, ctx)
        right = evaluate(node.right, ctx)
        ops = {
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            "<": lambda a, b: a < b,
            ">": lambda a, b: a > b,
            "<=": lambda a, b: a <= b,
            ">=": lambda a, b: a >= b,
        }
        return ops[node.op](left, right)
    if isinstance(node, Call):
        return _eval_call(node, ctx)
    raise FormulaError(f"Unknown AST node: {type(node)}")


def _eval_call(node: Call, ctx: FormulaContext) -> Any:
    """Evaluate a function call node."""
    name = node.name
    args = node.args

    if name == "floor":
        return math.floor(evaluate(args[0], ctx))
    if name == "ceil":
        return math.ceil(evaluate(args[0], ctx))
    if name == "abs":
        return abs(evaluate(args[0], ctx))
    if name == "max":
        return max(evaluate(a, ctx) for a in args)
    if name == "min":
        return min(evaluate(a, ctx) for a in args)

    if name == "sum":
        return sum(evaluate(a, ctx) for a in args)

    if name == "table":
        # table(table_name, index) — look up value by 1-based index
        if len(args) < 2:
            raise FormulaError("table() requires (table_name, index)")
        if not isinstance(args[0], Var):
            raise FormulaError("table() first arg must be a table name")
        table_name = args[0].parts[0]
        index = int(evaluate(args[1], ctx))
        if table_name not in ctx.tables:
            raise FormulaError(f"Unknown table: {table_name}")
        tbl = ctx.tables[table_name]
        if index < 1 or index > len(tbl):
            raise FormulaError(f"Table {table_name} index {index} out of range (1..{len(tbl)})")
        return tbl[index - 1]  # 1-based to 0-based

    if name == "per":
        # per(value, step) — ceiling division
        if len(args) < 2:
            raise FormulaError("per() requires (value, step)")
        value = evaluate(args[0], ctx)
        step = evaluate(args[1], ctx)
        if step == 0:
            raise FormulaError("per() step cannot be zero")
        return math.ceil(value / step)

    if name == "ratio":
        # ratio(ranks, cost_per_rank) — fractional cost: ceil(ranks * cost)
        if len(args) < 2:
            raise FormulaError("ratio() requires (ranks, cost_per_rank)")
        ranks = evaluate(args[0], ctx)
        cost = evaluate(args[1], ctx)
        return math.ceil(ranks * cost)

    if name == "if":
        # if(condition, then_value, else_value)
        if len(args) < 3:
            raise FormulaError("if() requires (condition, then, else)")
        cond = evaluate(args[0], ctx)
        if cond:
            return evaluate(args[1], ctx)
        return evaluate(args[2], ctx)

    raise FormulaError(f"Unknown function: {name}")


# ---------------------------------------------------------------------------
# Convenience: parse + evaluate in one call
# ---------------------------------------------------------------------------

def calc(expr: str, ctx: FormulaContext | None = None) -> Any:
    """Parse and evaluate a formula string."""
    if ctx is None:
        ctx = FormulaContext()
    return evaluate(parse(expr), ctx)
