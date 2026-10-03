from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from .store import ProposalStore


def create_app() -> FastAPI:
    app = FastAPI(title="PolyBridge backend", version="0.1.0")
    app.state.store = ProposalStore()
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    return app


app = create_app()
