"""The research link agent (`research/linker/link_map.py`, `options.py`), imported, not copied.

The rule parser and the link rules live with the studies that froze them (S11, S21, ladder_replay). The backend loads
them lazily from the repository's `research/` folder; the folder is appended to the end of `sys.path` so it never
shadows a backend module, and any path an imported study prepends (S21 adds `research/arb`) is moved to the end too.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import ModuleType

RESEARCH = Path(__file__).resolve().parents[3] / "research"
_LOCK = threading.Lock()
_MODS: tuple[ModuleType, ModuleType] | None = None
_ERROR: str | None = None


def load() -> tuple[ModuleType, ModuleType]:
    """(linker.link_map, linker.options). Raises RuntimeError with the reason when the research code is unavailable."""
    global _MODS, _ERROR
    with _LOCK:
        if _MODS is not None:
            return _MODS
        if _ERROR is not None:
            raise RuntimeError(_ERROR)
        before = list(sys.path)
        if str(RESEARCH) not in sys.path:
            sys.path.append(str(RESEARCH))
        try:
            from linker import link_map, options  # noqa: PLC0415
        except Exception as e:  # missing folder or dependency: callers report it, never crash
            _ERROR = f"research link agent unavailable: {type(e).__name__}: {e}"
            raise RuntimeError(_ERROR) from None
        finally:
            added = [p for p in sys.path if p not in before]
            sys.path[:] = [p for p in sys.path if p in before] + added
        _MODS = (link_map, options)
        return _MODS


def link_map() -> ModuleType:
    return load()[0]


def options() -> ModuleType:
    return load()[1]
