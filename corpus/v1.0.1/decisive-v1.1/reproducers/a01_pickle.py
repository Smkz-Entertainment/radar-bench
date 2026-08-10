"""Reproduce the pandas #55137 pickle compatibility regression."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", type=Path)
    parser.add_argument("--read", type=Path)
    args = parser.parse_args()
    if (args.write is None) == (args.read is None):
        parser.error("choose exactly one of --write or --read")
    if args.write is not None:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(np.ones((100, 4))).to_pickle(args.write)
        return 0
    frame = pd.read_pickle(args.read)  # nosec B301 - sealed historical reproducer
    if frame.shape != (100, 4) or not bool(frame.to_numpy().all()):
        raise AssertionError("historical pickle did not round-trip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
