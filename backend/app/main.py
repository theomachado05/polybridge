from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from .store import ProposalStore
from .markets import router as markets_router
from .verdicts import router as verdicts_router


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Drop echoed `input`/`ctx`: a rejected Infinity/NaN input is not JSON-serializable.
    detail = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})


def create_app() -> FastAPI:
    app = FastAPI(title="PolyBridge backend", version="0.1.0")
    app.state.store = ProposalStore()
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(router)
    app.include_router(verdicts_router)
    app.include_router(markets_router)
    return app


app = create_app()
