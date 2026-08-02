"""V9-compatible per-call ledger. Same schema as llm_gatewayV9/db.py, but
the database lives under ~/.glc/ so the gateway is installable as a daemon
without writing into the source tree.

Note: this is the *worker call* ledger, used by /v1/cost/by_agent. The
audit log (every channel message, policy verdict, tool dispatch) is a
separate append-only store under glc/audit/store.py.
"""

from __future__ import annotations

import contextvars
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DIR = Path(os.path.expanduser("~/.glc"))


def _resolve_db_path() -> str:
    """Resolve at call time (not import time) so a redirected config dir is
    honored and tests that swap the env var see the change. Precedence:
    explicit GLC_GATEWAY_DB > GLC_CONFIG_DIR/gateway.sqlite > ~/.glc.
    (Same config-dir honoring as the audit store — #74.)"""
    explicit = os.getenv("GLC_GATEWAY_DB")
    if explicit:
        return explicit
    cfg = os.getenv("GLC_CONFIG_DIR")
    if cfg:
        return str(Path(cfg) / "gateway.sqlite")
    return str(DEFAULT_DIR / "gateway.sqlite")

# --------------------------------------------------------------------------
# Cost-ledger input validation (leak10 / #19 — rraghu214)
#
# log_call() writes cost-ledger rows. Callers (channel adapters, /v1/chat
# clients) must not be able to poison the ledger with negative or absurd
# token counts, an unknown provider, or a forged agent label:
#   * token/count fields are validated non-negative and bounded;
#   * the provider must be a known one (or an internal sentinel);
#   * the agent is attributed server-side when a request context set it,
#     and is sanitized/bounded regardless of source.
# --------------------------------------------------------------------------

# Generous upper bound for any per-call count field. Real calls are orders
# of magnitude below this; anything above is a bug or an attempt to distort
# the ledger.
_MAX_COUNT = 100_000_000
# Latency is a count of milliseconds; cap at one week to catch garbage
# without rejecting a genuinely slow/hung call.
_MAX_LATENCY_MS = 7 * 24 * 3600 * 1000
# Bound free-text label fields so a caller cannot store megabytes per row.
_MAX_LABEL_LEN = 128

# Internal, server-generated provider sentinels used by the router / embed
# error paths (e.g. "(any)", "(none)", "(unavailable)", "(skipped)").
def _is_sentinel_provider(p: str) -> bool:
    return p.startswith("(") and p.endswith(")")


def _known_providers() -> set[str]:
    # Sourced from the pricing table so the two never drift.
    from glc import pricing as _pricing

    return set(_pricing.PRICING_USD_PER_MTOK)


def _validate_count(name: str, val, cap: int = _MAX_COUNT) -> int:
    # bool is an int subclass; reject it explicitly so True/False can't be
    # smuggled in as 1/0 counts.
    if isinstance(val, bool) or not isinstance(val, int):
        raise ValueError(f"{name} must be a non-negative int, got {val!r}")
    if val < 0:
        raise ValueError(f"{name} must be >= 0, got {val}")
    if val > cap:
        raise ValueError(f"{name} exceeds maximum {cap}, got {val}")
    return val


def _validate_provider(provider) -> str:
    if not isinstance(provider, str) or not provider:
        raise ValueError(f"provider must be a non-empty str, got {provider!r}")
    if _is_sentinel_provider(provider):
        return provider
    if provider not in _known_providers():
        raise ValueError(f"unknown provider {provider!r}")
    return provider


def _sanitize_label(val):
    """Bound and de-fang a free-text label (agent/session). Never raises —
    a too-long or control-char-laden label is truncated/stripped rather
    than dropped, so cost attribution still records *something*."""
    if val is None:
        return None
    s = str(val).replace("\n", " ").replace("\r", " ").strip()
    return s[:_MAX_LABEL_LEN] or None


# Server-side agent attribution. A request handler that has authenticated
# the caller can bind the trusted agent identity here; log_call() then
# prefers it over any caller-supplied `agent`, so the ledger attributes
# work to the server-established identity, not to wire input.
_current_agent: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "glc_current_agent", default=None
)


def set_call_agent(agent: str | None) -> None:
    """Bind the server-attributed agent for the current context (async-safe)."""
    _current_agent.set(_sanitize_label(agent))


def _ensure_parent(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def conn():
    path = _resolve_db_path()
    _ensure_parent(path)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init() -> None:
    with conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cache_create_tokens INTEGER DEFAULT 0,
                cache_read_tokens INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                status TEXT,
                error TEXT,
                prompt_chars INTEGER DEFAULT 0,
                response_chars INTEGER DEFAULT 0,
                override TEXT,
                attempted TEXT,
                tool_calls INTEGER DEFAULT 0,
                reasoning_applied INTEGER DEFAULT 0,
                tool_dialect TEXT,
                call_role TEXT DEFAULT 'worker',
                router_decision TEXT,
                embed_dim INTEGER,
                agent TEXT,
                session TEXT,
                retries INTEGER DEFAULT 0
            )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON calls(ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_prov_ts ON calls(provider, ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_role_ts ON calls(call_role, ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_agent_ts ON calls(agent, ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_session_ts ON calls(session, ts DESC)")


def log_call(
    provider,
    model,
    input_tokens=0,
    output_tokens=0,
    latency_ms=0,
    status="ok",
    error=None,
    prompt_chars=0,
    response_chars=0,
    override=None,
    attempted=None,
    cache_create_tokens=0,
    cache_read_tokens=0,
    tool_calls=0,
    reasoning_applied=False,
    tool_dialect=None,
    call_role="worker",
    router_decision=None,
    embed_dim=None,
    agent=None,
    session=None,
    retries=0,
) -> None:
    # --- validate/normalize before we touch the ledger (leak10 / #19) ---
    provider = _validate_provider(provider)
    input_tokens = _validate_count("input_tokens", input_tokens)
    output_tokens = _validate_count("output_tokens", output_tokens)
    cache_create_tokens = _validate_count("cache_create_tokens", cache_create_tokens)
    cache_read_tokens = _validate_count("cache_read_tokens", cache_read_tokens)
    tool_calls = _validate_count("tool_calls", tool_calls)
    retries = _validate_count("retries", retries)
    prompt_chars = _validate_count("prompt_chars", prompt_chars)
    response_chars = _validate_count("response_chars", response_chars)
    latency_ms = _validate_count("latency_ms", latency_ms, cap=_MAX_LATENCY_MS)
    if embed_dim is not None:
        embed_dim = _validate_count("embed_dim", embed_dim)

    # Attribute the agent server-side when a context has bound it; fall back
    # to a sanitized/bounded caller value otherwise. Never trust wire input
    # verbatim for cost attribution.
    server_agent = _current_agent.get()
    agent = server_agent if server_agent is not None else _sanitize_label(agent)
    session = _sanitize_label(session)

    with conn() as c:
        c.execute(
            """INSERT INTO calls (ts, provider, model, input_tokens, output_tokens,
                                  cache_create_tokens, cache_read_tokens,
                                  latency_ms, status, error, prompt_chars, response_chars,
                                  override, attempted, tool_calls, reasoning_applied, tool_dialect,
                                  call_role, router_decision, embed_dim,
                                  agent, session, retries)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                time.time(),
                provider,
                model,
                input_tokens,
                output_tokens,
                cache_create_tokens,
                cache_read_tokens,
                latency_ms,
                status,
                error,
                prompt_chars,
                response_chars,
                override,
                attempted,
                tool_calls,
                1 if reasoning_applied else 0,
                tool_dialect,
                call_role,
                router_decision,
                embed_dim,
                agent,
                session,
                retries,
            ),
        )


def by_agent(session=None, since=None):
    where = ["ts >= ?"]
    # Day-rollover fix: bucket by calendar day, not by 24h window.
    args = [since if since is not None else (time.time() - (time.time() % 86400))]
    if session:
        where.append("session=?")
        args.append(session)
    q = (
        "SELECT agent, provider, COUNT(*) AS calls, "
        "SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok, "
        "SUM(latency_ms) AS total_latency_ms, "
        "SUM(retries) AS total_retries, "
        "SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok, "
        "SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors "
        "FROM calls WHERE " + " AND ".join(where) + " AND agent IS NOT NULL "
        "GROUP BY agent, provider"
    )
    with conn() as c:
        rows = c.execute(q, args).fetchall()
        out: dict[str, list[dict]] = {}
        for r in rows:
            out.setdefault(r["agent"], []).append(dict(r))
        return out


def recent(limit=100, provider=None, status=None):
    q = "SELECT * FROM calls"
    where, args = [], []
    if provider:
        where.append("provider=?")
        args.append(provider)
    if status:
        where.append("status=?")
        args.append(status)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    with conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def aggregate(call_role=None):
    now = time.time()
    day_start = now - (now % 86400)
    q = """SELECT provider,
                  COUNT(*) AS calls,
                  SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok_calls,
                  SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors,
                  SUM(input_tokens) AS in_tok,
                  SUM(output_tokens) AS out_tok,
                  SUM(cache_read_tokens) AS cache_reads,
                  SUM(cache_create_tokens) AS cache_creates,
                  SUM(tool_calls) AS tool_calls,
                  AVG(latency_ms) AS avg_latency,
                  MAX(ts) AS last_ts
             FROM calls WHERE ts >= ?"""
    args = [day_start]
    if call_role == "worker":
        q += " AND (call_role='worker' OR call_role IS NULL)"
    elif call_role == "router":
        q += " AND call_role LIKE 'router%'"
    elif call_role:
        q += " AND call_role=?"
        args.append(call_role)
    q += " GROUP BY provider"
    with conn() as c:
        rows = c.execute(q, args).fetchall()
        return {r["provider"]: dict(r) for r in rows}
