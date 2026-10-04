from __future__ import annotations

import logging
import os
from typing import Any

from polybridge_research.massive import MissingApiKey, load_api_key

from .models import Account, Broker, BrokerError, Order, OrderRequest, Position
from .quotes import MassiveQuotes, NullQuotes
from .sim import DEFAULT_PATH, START_CASH, SimBroker
from .webull import SANDBOX_HOST, SIM_NOTE, NotSandboxHost, WebullBroker, WebullClient

__all__ = ["Account", "Broker", "BrokerError", "Order", "OrderRequest", "Position", "SimBroker", "WebullBroker",
           "WebullClient", "get_broker", "build_broker", "reset_default_broker"]

log = logging.getLogger(__name__)
_DEFAULT: Broker | None = None


def _env(name: str) -> str:
    try:
        return load_api_key(name, interactive=False)
    except MissingApiKey:
        return ""


def _on(name: str) -> bool:
    return _env(name).lower() in ("1", "true", "yes", "on")


def _quotes(app: Any | None):
    from .. import chain

    def client():
        c = getattr(getattr(app, "state", None), "massive", chain)
        return chain.make_client() if c is chain else c
    return MassiveQuotes(client)


def build_broker(app: Any | None = None) -> Broker:
    path = os.environ.get("SIM_ACCOUNT_PATH") or DEFAULT_PATH
    try:
        cash = float(os.environ.get("SIM_START_CASH") or START_CASH)
    except ValueError:
        cash = START_CASH
    if _env("BROKER").lower() == "webull":
        key, secret = _env("WEBULL_APP_KEY") or _env("WEBULL_API_KEY"), _env("WEBULL_APP_SECRET")
        if key and secret:
            try:
                client = WebullClient(key, secret, _env("WEBULL_BASE_URL") or SANDBOX_HOST,
                                      algorithm=_env("WEBULL_SIGN_ALG") or "HMAC-SHA256")
            except NotSandboxHost as e:
                log.error("%s; using the simulated broker", e)
                return SimBroker(path, _quotes(app), cash)
            sim = SimBroker(path, _quotes(app), cash, order_note=SIM_NOTE)
            return WebullBroker(client, sim, account_id=_env("WEBULL_ACCOUNT_ID") or None,
                                extended_hours=_on("WEBULL_EXTENDED_HOURS"), options_supported=_on("WEBULL_OPTIONS"))
        log.warning("BROKER=webull but WEBULL_APP_KEY / WEBULL_APP_SECRET are not set; using the simulated broker")
    return SimBroker(path, _quotes(app), cash)


def get_broker(app: Any | None = None) -> Broker:
    global _DEFAULT
    state = getattr(app, "state", None)
    if state is not None:
        b = getattr(state, "broker", None)
        if b is None:
            b = state.broker = build_broker(app)
        return b
    if _DEFAULT is None:
        _DEFAULT = build_broker(None)
    return _DEFAULT


def reset_default_broker() -> None:
    global _DEFAULT
    _DEFAULT = None
