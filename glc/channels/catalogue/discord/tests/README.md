# Discord — Live Testing & Setup (Member 11)

This folder holds the **live integration** pieces for the Discord adapter:
scripts and tests that exercise the adapter against the *real* Discord API,
plus the developer setup they depend on. The mock-based contract tests live
separately at `tests/channels/test_discord.py`; nothing here is required for
that suite to pass — these are opt-in and skip cleanly without credentials.

## Contents

| File | Purpose |
|---|---|
| `run_discord_bridge.py` | Live bridge: connects to the Discord Gateway (WebSocket) **and** the local GLC gateway, forwarding messages both ways. Also defines `RealDiscordClient` (REST send + `get_user`). |
| `send_test_message.py` | Standalone one-shot: POSTs a single test message to a channel via `RealDiscordClient`. Fastest way to confirm credentials work. |
| `test_live_discord.py` | Pytest live suite, marked `@pytest.mark.requires_live_api`. Auto-skips when credentials are absent, so CI stays green. |

## What changed in this PR

These files existed but were **non-functional** because they had been moved
into the `tests/` subpackage without updating their path references. This PR
makes them work:

1. **Import paths corrected** — `test_live_discord.py` and `send_test_message.py`
   imported `RealDiscordClient` from `...discord.run_discord_bridge` (slot root),
   but the module lives at `...discord.tests.run_discord_bridge`. The old path
   raised `ModuleNotFoundError` at collection time, so `test_live_discord.py`
   *errored* instead of skipping. Fixed to the `...discord.tests.*` path.

2. **`.env` load paths corrected** — all three files computed the repo root with
   the wrong number of parent hops (they assumed the slot-root location, one
   level shallower than `tests/`). `send_test_message.py` / `run_discord_bridge.py`
   looked in `glc/.env`; `test_live_discord.py` looked *above* the repo. All now
   use `Path(__file__).resolve().parents[5] / ".env"`, which resolves to the
   repository root regardless of the caller's working directory.

3. **README run commands updated** — the slot `README.md` `python -m ...`
   invocations now point at `...discord.tests.run_discord_bridge` /
   `...discord.tests.send_test_message`, and the "Files in this Slot" list
   reflects the `tests/` locations.

4. **`env.example` added** — a committable, placeholder-only template
   (`glc/channels/catalogue/discord/env.example`) documenting the three
   environment variables and where to obtain each. Named without a leading dot
   so the repo's `.env.*` ignore rule doesn't hide it.

No production code (`adapter.py`, `schemas.py`) was changed.

## Setup

1. Create a Discord application + bot in the
   [Developer Portal](https://discord.com/developers/applications), copy the
   **bot token**, and under *Privileged Gateway Intents* enable
   **Message Content Intent** and **Server Members Intent**.
2. Invite the bot to a server you own (OAuth2 → `bot` scope; permissions:
   View Channels, Send Messages, Read Message History). Ensure
   *Requires OAuth2 Code Grant* is **off** on the Bot page.
3. Enable **Developer Mode** in the Discord app (User Settings → Advanced) and
   copy a **channel ID** (right-click channel) and a **user ID** (right-click
   user).
4. Copy the template and fill in real values:
   ```bash
   cp glc/channels/catalogue/discord/env.example .env   # at repo root
   ```
   ```env
   DISCORD_BOT_TOKEN=...
   DISCORD_TEST_CHANNEL_ID=...
   DISCORD_TEST_USER_ID=...
   ```
   `.env` is git-ignored — never commit it.

Full walkthrough with screenshots: `../help_docs/discord_channel_bot.md`.

## Testing

### Mock contract tests (no credentials, always run)
```bash
uv run pytest tests/channels/test_discord.py -v
```

### Quick live sanity check — one REST send
Needs `DISCORD_BOT_TOKEN` + `DISCORD_TEST_CHANNEL_ID`. Posts a message to the
channel and prints the returned message ID:
```bash
uv run python -m glc.channels.catalogue.discord.tests.send_test_message
```

### Live pytest suite
```bash
uv run pytest glc/channels/catalogue/discord/tests/test_live_discord.py -m requires_live_api -v
```
- With no `.env`, both tests **skip** (no error) — this is the CI-safe default.
- With credentials set:
  - `test_send_real_message` — `adapter.send()` posts to a real channel and
    the response contains a message `id` (and is not a 429).
  - `test_get_user_resolves_handle` — `RealDiscordClient.get_user()` returns a
    dict with `id` and `username` for `DISCORD_TEST_USER_ID`.

### Full end-to-end bridge (optional)
Start the gateway (`uv run python -m glc.main`) in one terminal, then:
```bash
uv run python -m glc.channels.catalogue.discord.tests.run_discord_bridge
```
Post a message in your Discord channel and watch it flow through the adapter to
the GLC gateway and back.

### Troubleshooting
- **`DISCORD_BOT_TOKEN is not set`** — `.env` isn't at the repo root, or the key
  is empty/placeholder.
- **`403 Forbidden`** on send — the bot lacks Send Messages permission in that
  channel.
- **`404 Not Found`** on send — `DISCORD_TEST_CHANNEL_ID` doesn't match a channel
  the bot can see.
