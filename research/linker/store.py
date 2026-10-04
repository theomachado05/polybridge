"""Where the link agent's cached pulls live. New pulls go to `linker/.cache` (not committed); files that S5 or S4
already pulled are read from their caches, so nothing is fetched twice.

File names follow S5: `pm_<market number>.npz` (odds: t, p), `eq_<TICKER>.npz` (5-minute bars), `day_<TICKER>.npz`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
NEW = HERE / ".cache"
READ = (NEW, HERE.parent / "s5_big_moves" / ".cache", HERE.parent / "s4_linked_assets" / ".cache")


def find(name: str) -> Path | None:
    """The first cache that holds `name`, or None."""
    for d in READ:
        if (d / name).exists():
            return d / name
    return None


def npz(name: str) -> dict | None:
    f = find(name)
    return dict(np.load(f)) if f else None


def save(name: str, **arrays) -> Path:
    NEW.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(NEW / name, **arrays)
    return NEW / name
