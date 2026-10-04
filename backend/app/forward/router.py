from __future__ import annotations

from fastapi import APIRouter

from . import status

router = APIRouter()


@router.get("/forward/status")
def forward_status() -> dict:
    return status.build()
