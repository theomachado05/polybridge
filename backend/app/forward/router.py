from __future__ import annotations

from fastapi import APIRouter

from . import status

router = APIRouter()


@router.get("/forward/status")
def forward_status() -> dict:
    """Latest forward-test snapshots (ladder live check, touch-ticket state), each labelled with the frozen rule files
    (path, commit). Read-only: runs happen through `make forward-ladders` / `make forward-touch`."""
    return status.build()
