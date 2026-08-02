"""FastAPI app for glc_v1. Port 8111 by default. V9 routes are mounted
as-is (S9 Browser / S10 Computer-Use clients work unchanged); the new
S11 surfaces (transcribe, speak, channels WS, control) sit alongside.
"""

from __future__ import annotations
import hmac
import os
import signal
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = Path(__file__).parent
load_dotenv(ROOT.parent / ".env")  # repo .env, if present

from glc import db  # noqa: E402
from glc import embedders as E  # noqa: E402
from glc import providers as P  # noqa: E402
from glc.audit import init_store as init_audit  # noqa: E402
from glc.cache import GeminiCache  # noqa: E402
from glc.config import get_or_create_install_token  # noqa: E402
from glc.policy import reload_engine  # noqa: E402
from glc.routes import channels as channels_route  # noqa: E402
from glc.routes import chat as chat_route  # noqa: E402
from glc.routes import control as control_route  # noqa: E402
from glc.routes import speak as speak_route  # noqa: E402
from glc.routes import transcribe as transcribe_route  # noqa: E402
from glc.routing import Router, RouterPool  # noqa: E402

PORT = int(os.getenv("GLC_PORT", "8111"))

DATA_PLANE_PATHS = {
    "/v1/chat",
    "/v1/chat/batch",
    "/v1/vision",
    "/v1/embed",
    "/v1/embedders",
    "/v1/cost-by-agent",
    "/v1/providers",
    "/v1/capabilities",
    "/v1/routers",
    "/v1/calls",
    "/v1/status",
    "/v1/transcribe",
    "/v1/speak" 
}

CONTROL_PLANE_PATHS = {
    "/v1/control/pair",
    "/v1/control/pair/confirm",
    "/v1/control/presence",
    "/v1/control/kill",
}

PROTECTED_PATHS = DATA_PLANE_PATHS | CONTROL_PLANE_PATHS
def _extract_bearer_token(request:Request) -> str :
    """Extracts the bearer token from the Authorization header."""
    auth_header = request.headers.get("Authorization","")
    if auth_header.startswith("Bearer "):
        return auth_header.removeprefix("Bearer ").strip()
    return ""
def _docs_enabled() -> bool:
    """Returns True if the OpenAPI docs should be enabled."""
    return bool(os.getenv("GLC_DOCS_ENABLED", "") .strip())
def _install_sighup_reload() -> None:
    """Hot-reload policy.yaml on SIGHUP. Windows lacks SIGHUP so this is
    a no-op there."""
    if not hasattr(signal, "SIGHUP"):
        return

    def _handler(signum, frame):  # noqa: ARG001
        try:
            reload_engine()
            print("[glc] policy.yaml reloaded via SIGHUP")
        except Exception as e:
            print(f"[glc] SIGHUP reload failed: {e!r}")

    try:
        signal.signal(signal.SIGHUP, _handler)
    except ValueError:
        # signal() only works on the main thread; tests using TestClient
        # spawn lifespan from a worker thread. Silent skip is correct here.
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    init_audit()
    get_or_create_install_token()
    _install_sighup_reload()
    app.state.cache = GeminiCache(ttl_seconds=300)
    app.state.providers = P.build_providers(app.state.cache)
    app.state.router = Router(app.state.providers, chat_route.ORDER)
    app.state.router_providers = P.build_router_providers()
    app.state.router_pool = RouterPool(app.state.router_providers, chat_route.ROUTER_ORDER)
    app.state.embedders, app.state.embed_order = E.build_embedders()
    app.state.started_at = time.time()
    app.state.registered_channels = []
    yield


app = FastAPI(
    title="GLC v1 — Gateway for LLMs and Channels", 
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled() else None,
    redoc_url="/redoc" if _docs_enabled() else None, 
    openapi_url="/openapi.json" if _docs_enabled() else None,       
)           

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Middleware to enforce bearer token authentication for control-plane paths."""
    if request.url.path in CONTROL_PLANE_PATHS:
        expected = os.getenv("GLC_CONTROL_TOKEN","")
    elif request.url.path in DATA_PLANE_PATHS:
        expected = os.getenv("GLC_API_TOKEN","")
    else:
        return await call_next(request)
    if not expected:
        return JSONResponse(
            {"detail": "gateway auth is not configured (GLC_" + ("CONTROL_TOKEN" if request.url.path in CONTROL_PLANE_PATHS else "API_TOKEN") + " unset)"},
            status_code=503,
        )
    presented = _extract_bearer_token(request)
    if not presented or not hmac.compare_digest(presented, expected):
        return JSONResponse(
            {"detail": "missing or invalid bearer token "},
            status_code=401
        )
    
    response = await call_next(request)
    return response
app.include_router(chat_route.router)
app.include_router(transcribe_route.router)
app.include_router(speak_route.router)
app.include_router(control_route.router)
app.include_router(channels_route.router)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (
        "<html><body style='font-family:sans-serif;max-width:680px;margin:2em auto'>"
        "<h1>GLC v1</h1>"
        "<p>Gateway for LLMs and Channels — Session 11 scaffold.</p>"
        "<p>Open <code>/docs</code> for the OpenAPI explorer.</p>"
        "<p>Channel adapters connect over <code>WS /v1/channels/&lt;name&gt;</code>."
        " V9 callers should point at this port unchanged: chat, vision, embed,"
        " batch, cost-by-agent, providers, capabilities, status, calls."
        "</p>"
        "</body></html>"
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True, "port": PORT}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("glc.main:app", host="0.0.0.0", port=PORT, reload=False)
