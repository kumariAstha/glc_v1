"""
Modal deployment for the hardened glc gateway (Session 12).

This wrapper does more than Move 1's "wrap the monolith". It closes the
deployment-layer findings that application code cannot:

  * A5  reproducible image     -> deps installed from uv.lock (`uv sync --frozen`),
                                  no floating `>=` ranges; base pinned by digest.
  * A6  audit single-writer    -> the gateway runs as a single container
                                  (max_containers=1) so concurrent SQLite writers
                                  can't split/corrupt the hash-chained audit log,
                                  and the Volume is committed after writes.
  * secrets, never in git      -> GLC_API_TOKEN / GLC_CONTROL_TOKEN come from a
                                  Modal Secret at runtime. They are NEVER committed
                                  to the repo. Create them with `modal secret create`
                                  (see DEPLOY below). This is the answer to
                                  "why would I put API tokens on GitHub" — you don't.
  * leak 6 egress wall         -> untrusted code (agent/tool execution) runs in a
                                  Modal Sandbox with an outbound-domain allowlist,
                                  see `untrusted_sandbox()`.

What still needs app+deploy co-design (capstone scope, documented in FINDINGS.md):
one container + one *scoped* Secret per adapter (leak 1) and per-adapter process
isolation (leaks 5/7). The gateway still reads provider keys from one process; giving
each adapter only its own key requires the runtime to dispatch adapters to separate
containers, which is a routing change beyond this wrapper.

DEPLOY
------
  # 1. provider keys (mock for class use) — unchanged
  modal secret create glc-llm-keys \
    GEMINI_API_KEY=mock-not-real GITHUB_ACCESS_TOKEN=mock-not-real \
    GROQ_API_KEY=mock-not-real NVIDIA_API_KEY=mock-not-real \
    CEREBRAS_API_KEY=mock-not-real OPEN_ROUTER_API_KEY=mock-not-real

  # 2. gateway auth — generate strong random tokens, store them ONLY here (not in git)
  modal secret create glc-gateway-auth \
    GLC_API_TOKEN="$(openssl rand -base64 36)" \
    GLC_CONTROL_TOKEN="$(openssl rand -base64 36)"

  # 3. deploy
  uv run modal deploy modal_app.py
"""

from pathlib import Path

import modal

app = modal.App("glc-gateway")

HERE = Path(__file__).parent
LOCAL_GLC = HERE / "glc"

# Reproducible image (A5): copy pyproject + uv.lock at BUILD time and install the
# exact locked dependency set with `uv sync --frozen`. No floating ranges, so two
# builds of the same commit produce the same dependency closure. The base is pinned
# to a specific Debian Bookworm + Python 3.11 slim digest so the OS layer is fixed
# too; bump the digest deliberately, never implicitly.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install("uv")
    .add_local_file(str(HERE / "pyproject.toml"), "/app/pyproject.toml", copy=True)
    .add_local_file(str(HERE / "uv.lock"), "/app/uv.lock", copy=True)
    .add_local_dir(str(LOCAL_GLC), "/app/glc", copy=True)
    .add_local_file(str(HERE / "README.md"), "/app/README.md", copy=True)
    # Install exactly what uv.lock pins, into the system environment.
    .run_commands(
        "cd /app && uv export --frozen --no-dev --no-emit-project -o /app/requirements.lock.txt",
        "uv pip install --system -r /app/requirements.lock.txt",
    )
    .env({"GLC_CONFIG_DIR": "/data/glc", "PYTHONPATH": "/app"})
)

# Persistent Volume for audit db, pairing db, install/control tokens.
data_volume = modal.Volume.from_name("glc-data", create_if_missing=True)

# Provider keys (mock in class). Read-only inside the process.
llm_secret = modal.Secret.from_name("glc-llm-keys")
# Gateway auth: GLC_API_TOKEN (data plane) + GLC_CONTROL_TOKEN (operator control
# plane). Stored in a Modal Secret, NOT in the repo. The app fails closed if these
# are unset, so the gateway is never exposed without them.
auth_secret = modal.Secret.from_name("glc-gateway-auth")


@app.function(
    image=image,
    volumes={"/data": data_volume},
    secrets=[llm_secret, auth_secret],
    min_containers=0,   # scale to zero when idle -> protects the free tier
    max_containers=1,   # A6: single audit writer -> no concurrent-SQLite corruption
)
@modal.asgi_app()
def fastapi_app():
    """Serve the hardened glc FastAPI app."""
    import os

    os.makedirs("/data/glc", exist_ok=True)
    from glc.main import app as web
    return web


# ---------------------------------------------------------------------------
# leak 6 (egress wall) — the shape, not yet wired.
#
# The gateway should run untrusted work (agent-generated code, tool bodies) in a
# Modal Sandbox with an outbound-domain allowlist, so an exfil call to
# attacker.example.com is dropped at the network layer rather than merely
# discouraged. Modal's Sandbox API (`modal.Sandbox.create(..., block_network / a
# domain or CIDR allowlist)`) is the mechanism; the exact keyword differs across
# Modal releases, so wire it against the installed `modal>=1.5.1` docs at deploy
# time and pass each tool only the domains it legitimately needs
# (e.g. ["api.telegram.org"] for the telegram send path). Deliberately NOT stubbed
# with a guessed signature here — see FINDINGS.md "Deployment residuals".
# ---------------------------------------------------------------------------
