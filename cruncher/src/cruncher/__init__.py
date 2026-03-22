"""Cruncher — domain-agnostic TTRPG rules engine.

Pure computation: formulas, stacking, character building, stat derivation, dice.
No DB, no network, no state. Takes dataclasses in, returns dataclasses out.
"""

from cruncher.build import BuildResult, process_build
from cruncher.dice import roll_expr
from cruncher.engine import CalcResult, recalculate
from cruncher.errors import CruncherError
from cruncher.formulas import FormulaContext, FormulaError, calc, parse
from cruncher.stacking import (
    ModifierEntry,
    StackingPolicy,
    decompose_modifiers,
    load_stacking_policy,
    resolve_stacking,
)
from cruncher.system_pack import SystemPack, load_system_pack
from cruncher.types import CharacterData

__all__ = [
    "BuildResult",
    "CalcResult",
    "CharacterData",
    "CruncherError",
    "FormulaContext",
    "FormulaError",
    "ModifierEntry",
    "StackingPolicy",
    "SystemPack",
    "calc",
    "decompose_modifiers",
    "load_stacking_policy",
    "load_system_pack",
    "parse",
    "process_build",
    "recalculate",
    "resolve_stacking",
    "roll_expr",
]
