"""Pathfinder 2e Remaster system pack for cruncher.

Open Game Content derived from the Pathfinder 2e SRD, licensed under
the ORC License. See the LICENSE file for details.
"""

from pathlib import Path


def pack_path() -> str:
    """Return the absolute path to the system pack data directory.

    Usage:
        import cruncher
        import cruncher_pf2e

        pack = cruncher.load_system_pack(cruncher_pf2e.pack_path())
    """
    return str(Path(__file__).parent / "data")
