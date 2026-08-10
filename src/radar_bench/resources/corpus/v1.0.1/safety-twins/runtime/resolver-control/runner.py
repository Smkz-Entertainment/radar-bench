from __future__ import annotations

import os
from pathlib import Path


profile = os.environ.get("RADAR_PROFILE", "")
side = os.environ.get("RADAR_SIDE", "")

if profile in {"01", "02", "03", "04", "05", "06", "07", "08", "17", "18"}:
    raise SystemExit(1)
if profile in {"09", "10", "11", "12"} and not Path("required.dat").is_file():
    raise SystemExit(1)
if profile in {"13", "14", "15", "16"}:
    if Path("resolver.lock").read_text(encoding="utf-8").strip() != "stable":
        raise SystemExit(1)
if profile in {"19", "20"} and os.environ.get("RADAR_PLATFORM") != "x86_64":
    raise SystemExit(1)
print("completed")
