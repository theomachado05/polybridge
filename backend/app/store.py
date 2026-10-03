"""In-memory proposal store. A proposal becomes executable only through approve(), exactly once."""
from __future__ import annotations

import datetime as dt
import threading
import uuid

from .models import Proposal


class NotFound(KeyError):
    pass


class AlreadyDecided(RuntimeError):
    pass


class ProposalStore:
    def __init__(self) -> None:
        self._items: dict[str, Proposal] = {}
        self._lock = threading.Lock()

    def propose(self, **fields) -> Proposal:
        p = Proposal(id=uuid.uuid4().hex[:12], status="proposed", created_at=dt.datetime.now(dt.UTC), **fields)
        with self._lock:
            self._items[p.id] = p
        return p

    def list(self) -> list[Proposal]:
        with self._lock:
            return list(self._items.values())

    def _decide(self, pid: str, status: str) -> Proposal:
        with self._lock:
            if pid not in self._items:
                raise NotFound(pid)
            current = self._items[pid]
            if current.status != "proposed":
                raise AlreadyDecided(pid)
            updated = current.model_copy(update={"status": status, "decided_at": dt.datetime.now(dt.UTC)})
            self._items[pid] = updated
            return updated

    def approve(self, pid: str) -> Proposal:
        return self._decide(pid, "approved")

    def reject(self, pid: str) -> Proposal:
        return self._decide(pid, "rejected")
