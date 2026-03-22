"""d20 Hero SRD (3e) system pack for cruncher.

Open Game Content derived from the d20 Hero SRD, licensed under the
Open Game License v1.0a. See the LICENSE file for details.
"""

from pathlib import Path


def pack_path() -> str:
    """Return the absolute path to the system pack data directory.

    Usage:
        import cruncher
        import cruncher_mm3e

        pack = cruncher.load_system_pack(cruncher_mm3e.pack_path())
    """
    return str(Path(__file__).parent / "data")
