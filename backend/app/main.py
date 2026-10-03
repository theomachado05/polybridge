from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from .store import ProposalStore
from .markets import router as markets_router
from .verdicts import router as verdicts_router
from .equities import router as equities_router
from .hedges import router as hedges_router
from .mapping import router as mapping_router
from .bridges import router as bridges_router
from .portfolio import router as portfolio_router
from .broker.routes import router as broker_router
from .security import guard_remote_writes


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Drop echoed `input`/`ctx`: a rejected Infinity/NaN input is not JSON-serializable.
    detail = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})


def create_app() -> FastAPI:
    app = FastAPI(title="PolyBridge backend", version="0.1.0")
    app.state.store = ProposalStore()
    app.middleware("http")(guard_remote_writes)  # remote (tunnelled) writes need X-Agent-Secret
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["*"], allow_headers=["*"])
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(router)
    app.include_router(verdicts_router)
    app.include_router(markets_router)
    app.include_router(equities_router)
    app.include_router(hedges_router)
    app.include_router(mapping_router)
    app.include_router(bridges_router)
    app.include_router(portfolio_router)
    from .pipeline.router import router as pipeline_router; app.include_router(pipeline_router)  # noqa: E702
    app.include_router(broker_router)
    from .options.router import router as options_router; app.include_router(options_router)  # noqa: E702
    from .agent import router as agent_router; app.include_router(agent_router)  # noqa: E702
    return app


app = create_app()
