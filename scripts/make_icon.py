"""Erzeugt assets/icon.ico fuer den Exe-Build."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from away_monitor.icon import ICO_SIZES, render  # noqa: E402

TARGET = ROOT / "assets" / "icon.ico"


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    image = render("#3ecf8e", size=256)
    image.save(TARGET, sizes=[(size, size) for size in ICO_SIZES])
    print(f"geschrieben: {TARGET} ({TARGET.stat().st_size} Bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
