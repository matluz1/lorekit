"""Shared argument parser for LoreKit cmd_* functions."""

from lorekit.db import LoreKitError


def parse_args(args, schema, positional=None):
    """Parse --key value pairs from an args list.

    Parameters
    ----------
    args : list[str]
        Raw argument list (e.g. ["1", "--name", "Mira", "--level", "5"]).
    schema : dict
        Mapping of flag -> (name, required, default).
        Example: {"--name": ("name", True, ""), "--level": ("level", False, "")}
    positional : str | None
        Name for the first positional argument (e.g. "session_id").
        If provided, args[0] is consumed as the positional value.
        If None, no positional is expected.

    Returns
    -------
    tuple[str | None, dict[str, str]]
        (positional_value, parsed_flags)

    Raises
    ------
    LoreKitError
        On missing required args or unknown flags.
    """
    pos_val = None
    start = 0
    if positional is not None:
        if not args:
            raise LoreKitError(f"{positional} required")
        pos_val = args[0]
        start = 1

    result = {name: default for _, (name, _, default) in schema.items()}
    i = start
    while i < len(args):
        if args[i] in schema:
            name, _, _ = schema[args[i]]
            if i + 1 >= len(args):
                raise LoreKitError(f"{args[i]} requires a value")
            result[name] = args[i + 1]
            i += 2
        else:
            raise LoreKitError(f"Unknown option: {args[i]}")

    for flag, (name, required, _) in schema.items():
        if required and not result[name]:
            raise LoreKitError(f"{flag} is required")

    return pos_val, result
