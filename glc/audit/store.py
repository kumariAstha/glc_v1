"""Append-only SQLite audit log.

Every channel message, agent decision, policy verdict, and tool dispatch
lands here. Append-only is enforced at the application layer: only
`append()` is exposed; there is no update or delete function. The schema
ships with `audit_schema` version 1; bumping it requires a documented
migration step (see schema.sql).

Each append commits immediately so writes survive a hard kill.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(os.path.expanduser("~/.glc"))

# Genesis link for the hash chain (prev_hash of the very first row).
_GENESIS = "0" * 64


def _resolve_path() -> str:
    """Resolve at call time, not import time, so tests that swap the env
    var see the change.

    Precedence (#74 — padmanabh275): an explicit GLC_AUDIT_DB wins; failing
    that, honor GLC_CONFIG_DIR so a Modal cold start that redirects the
    config dir keeps the audit trail in the same place instead of silently
    splitting/wiping it under a stale ~/.glc. Only when neither is set do we
    fall back to the hard-coded home dir.
    """
    explicit = os.getenv("GLC_AUDIT_DB")
    if explicit:
        return explicit
    cfg = os.getenv("GLC_CONFIG_DIR")
    if cfg:
        return str(Path(cfg) / "audit.sqlite")
    return str(DEFAULT_DIR / "audit.sqlite")


@contextmanager
def _conn():
    p = _resolve_path()
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, isolation_level=None)  # autocommit; each insert flushes
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _ensure_chain_columns(c: sqlite3.Connection) -> None:
    """Idempotently add the hash-chain columns. schema.sql ships without
    them (it is not editable here); we add them at the application layer so
    every writer participates in the chain (leak2)."""
    cols = {r["name"] for r in c.execute("PRAGMA table_info(audit_log)").fetchall()}
    if "prev_hash" not in cols:
        c.execute("ALTER TABLE audit_log ADD COLUMN prev_hash TEXT")
    if "row_hash" not in cols:
        c.execute("ALTER TABLE audit_log ADD COLUMN row_hash TEXT")


def init_store() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA_PATH.read_text())
        _ensure_chain_columns(c)


def _row_payload(
    *,
    ts: float,
    session_id: str | None,
    channel: str,
    channel_user_id: str,
    trust_level: str,
    event_type: str,
    tool: str | None,
    policy_verdict: str | None,
    params_json: str | None,
    result_json: str | None,
) -> str:
    """Canonical serialization of a row's semantic content. Any change to a
    stored field changes this string and therefore the row hash."""
    return json.dumps(
        [
            ts,
            session_id,
            channel,
            channel_user_id,
            trust_level,
            event_type,
            tool,
            policy_verdict,
            params_json,
            result_json,
        ],
        default=str,
        separators=(",", ":"),
    )


def _hash_row(prev_hash: str, payload: str) -> str:
    return hashlib.sha256(f"{prev_hash}|{payload}".encode()).hexdigest()


def _jsonify(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, default=str)
    except Exception:
        return json.dumps({"_repr": repr(v)})


class AuditStore:
    """Application-layer write-once store. The class deliberately exposes
    no update or delete methods. Reads (for the replay viewer) live in
    query() which is read-only.

    Each row is hash-chained (leak2): row_hash = sha256(prev_hash | payload),
    where prev_hash is the previous row's row_hash. Tampering with any
    stored field, or deleting/reordering a non-tail row, breaks the chain
    and is caught by verify_chain(). (OS/SQL-level DELETE cannot be
    prevented from within the app — that needs a read-only mount / Modal
    Secret isolation — but the chain makes such tampering *detectable*.)
    """

    def __init__(self) -> None:
        # Serialize appends so read-prev-hash + insert is atomic and the
        # chain has no races.
        self._lock = threading.Lock()

    def append(
        self,
        *,
        channel: str,
        channel_user_id: str,
        trust_level: str,
        event_type: str,
        session_id: str | None = None,
        tool: str | None = None,
        policy_verdict: str | None = None,
        params: Any = None,
        result: Any = None,
    ) -> int:
        ts = time.time()
        params_json = _jsonify(params)
        result_json = _jsonify(result)
        with self._lock, _conn() as c:
            _ensure_chain_columns(c)
            c.execute("BEGIN IMMEDIATE")
            try:
                prev = c.execute(
                    "SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1"
                ).fetchone()
                prev_hash = (prev["row_hash"] if prev and prev["row_hash"] else _GENESIS)
                payload = _row_payload(
                    ts=ts,
                    session_id=session_id,
                    channel=channel,
                    channel_user_id=channel_user_id,
                    trust_level=trust_level,
                    event_type=event_type,
                    tool=tool,
                    policy_verdict=policy_verdict,
                    params_json=params_json,
                    result_json=result_json,
                )
                row_hash = _hash_row(prev_hash, payload)
                cur = c.execute(
                    """INSERT INTO audit_log
                       (ts, session_id, channel, channel_user_id, trust_level,
                        event_type, tool, policy_verdict, params_json, result_json,
                        prev_hash, row_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        ts,
                        session_id,
                        channel,
                        channel_user_id,
                        trust_level,
                        event_type,
                        tool,
                        policy_verdict,
                        params_json,
                        result_json,
                        prev_hash,
                        row_hash,
                    ),
                )
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            return int(cur.lastrowid or 0)


_singleton: AuditStore | None = None


def get_store() -> AuditStore:
    global _singleton
    if _singleton is None:
        init_store()
        _singleton = AuditStore()
    return _singleton


def append(**kwargs: Any) -> int:
    return get_store().append(**kwargs)


def query(limit: int = 100, session_id: str | None = None, channel: str | None = None) -> list[dict]:
    q = "SELECT * FROM audit_log"
    where, args = [], []
    if session_id:
        where.append("session_id=?")
        args.append(session_id)
    if channel:
        where.append("channel=?")
        args.append(channel)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def schema_version() -> int:
    with _conn() as c:
        row = c.execute("SELECT MAX(version) AS v FROM audit_schema").fetchone()
        return int(row["v"] or 0)


def verify_chain() -> dict:
    """Walk the audit log in insertion order and verify the hash chain.

    Detects (a) tampering — any field of a row changed so its recomputed
    row_hash no longer matches the stored one; (b) deletion/reordering of a
    non-tail row — the next row's prev_hash no longer matches the actual
    previous row's row_hash.

    Returns {"ok": bool, "rows": int, "errors": [ {id, kind, detail}, ... ]}.
    """
    errors: list[dict] = []
    with _conn() as c:
        _ensure_chain_columns(c)
        rows = c.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()
        prev_hash = _GENESIS
        for r in rows:
            rid = r["id"]
            stored_prev = r["prev_hash"]
            stored_hash = r["row_hash"]
            if stored_hash is None:
                errors.append({"id": rid, "kind": "unchained", "detail": "row has no row_hash"})
                # Can't extend the chain past an unchained row.
                prev_hash = stored_hash or prev_hash
                continue
            # Linkage check: this row must point at the previous row's hash.
            if stored_prev != prev_hash:
                errors.append(
                    {
                        "id": rid,
                        "kind": "broken_link",
                        "detail": f"prev_hash={stored_prev!r} expected {prev_hash!r} "
                        "(row deleted, reordered, or inserted)",
                    }
                )
            # Content check: recompute the hash over this row's fields.
            payload = _row_payload(
                ts=r["ts"],
                session_id=r["session_id"],
                channel=r["channel"],
                channel_user_id=r["channel_user_id"],
                trust_level=r["trust_level"],
                event_type=r["event_type"],
                tool=r["tool"],
                policy_verdict=r["policy_verdict"],
                params_json=r["params_json"],
                result_json=r["result_json"],
            )
            recomputed = _hash_row(stored_prev or _GENESIS, payload)
            if recomputed != stored_hash:
                errors.append(
                    {"id": rid, "kind": "tampered", "detail": "row content does not match row_hash"}
                )
            prev_hash = stored_hash
    return {"ok": not errors, "rows": len(rows), "errors": errors}
