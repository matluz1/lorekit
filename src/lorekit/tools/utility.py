from lorekit._mcp_app import mcp
from lorekit.tools._helpers import _resolve_system_path_for_session, _run_with_db


@mcp.tool()
def roll_dice(expression: str) -> str:
    """Roll dice using tabletop notation. Format: [N]d<sides>[kh<keep>][+/-mod]. Separate multiple expressions with spaces."""
    from cruncher.dice import format_result, roll_expr
    from cruncher.errors import CruncherError
    from lorekit.db import LoreKitError

    expressions = expression.split()
    results = []
    for expr in expressions:
        try:
            r = roll_expr(expr)
            results.append((expr, r))
        except (LoreKitError, CruncherError) as e:
            return f"ERROR: {e}"

    if len(results) == 1:
        return format_result(results[0][1])
    blocks = []
    for expr, r in results:
        blocks.append(f"--- {expr} ---\n{format_result(r)}")
    return "\n\n".join(blocks)


@mcp.tool()
def recall_search(session_id: int, query: str, source: str = "", n: int = 0, mode: str = "semantic") -> str:
    """Search timeline and journal by meaning (semantic) or exact keyword match.

    mode: "semantic" (default) finds content by meaning. "keyword" finds exact text matches (case-insensitive).
    source: "timeline", "journal", or empty for both.
    n: override result count (0 = defaults). Only applies to semantic mode.
    """
    if mode == "keyword":
        from lorekit.db import LoreKitError, require_db
        from lorekit.narrative.journal import search as jn_search
        from lorekit.narrative.timeline import search as tl_search

        db = require_db()
        try:
            parts = []
            if source in ("", "timeline"):
                r = tl_search(db, session_id, query)
                if source == "":
                    parts.append("--- TIMELINE ---")
                parts.append(r)
            if source in ("", "journal"):
                r = jn_search(db, session_id, query)
                if source == "":
                    parts.append("\n--- JOURNAL ---")
                parts.append(r)
            return "\n".join(parts)
        except LoreKitError as e:
            return f"ERROR: {e}"
        finally:
            db.close()

    from lorekit.support.recall import search

    return _run_with_db(search, session_id, query, source, n)


def recall_reindex(session_id: int) -> str:
    """Rebuild vector collections from SQL data for a session."""
    from lorekit.support.recall import reindex

    return _run_with_db(reindex, session_id)


@mcp.tool()
def export_dump(session_id: int, clean_previous: bool = False) -> str:
    """Export all session data to .export/session_<id>.txt.

    clean_previous: if true, removes the .export/ directory before exporting.
    """
    if clean_previous:
        from lorekit.support.export import clean

        _run_with_db(clean)
    from lorekit.support.export import dump

    return _run_with_db(dump, session_id)


def export_clean() -> str:
    """Remove the .export/ directory and all files inside it."""
    from lorekit.support.export import clean

    return _run_with_db(clean)


@mcp.tool()
def rest(session_id: int, type: str) -> str:
    """Apply rest rules to all PCs in the session.

    type: rest type from system pack (e.g. "short", "long").
    Restores stats via formulas, resets ability uses, clears combat
    modifiers, and optionally advances time. All rules come from
    the system pack's "rest" section.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        system_path = _resolve_system_path_for_session(db, session_id)
        if not system_path:
            return "ERROR: No rules_system set for this session."

        from lorekit.rest import rest as _rest

        return _rest(db, session_id, type, system_path)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()
