# Discord Gateway Adapter

Slot `discord` (group **Discord**, chat `G2`). This module implements the Discord Gateway adapter for **Session 11 — GLC v1**.

It translates real-time Discord messaging events (WebSockets and REST APIs) to and from the canonical gateway message envelopes, featuring automatic trust classification, allowlist gating in public channels, and user mention resolution.

---

## Files in this Slot

* **`adapter.py`**: The core adapter implementation subclassing `ChannelAdapter`. Houses the `on_message` inbound event translator and the `send` outbound REST reply dispatcher.
* **`schemas.py`**: Pydantic models mirroring the actual slices of the Discord WebSocket gateway payload and REST bodies (e.g. `DiscordUser`, `DiscordMessage`, `DiscordCreateMessage`).
* **`help_docs/api_research.md`**: Architectural mapping of the Discord API payload parameters, REST endpoints, and required Authorization headers.
* **`tests/run_discord_bridge.py`**: A live client bridge runner that connects to the Discord WebSocket Gateway and bridges messages to/from the local GLC Gateway server.
* **`tests/send_test_message.py`**: A standalone test helper script to send test REST API messages directly to a target Discord channel.
* **`tests/test_live_discord.py`**: Live integration tests (marked `requires_live_api`) that exercise the real Discord REST API; auto-skipped when credentials are absent.

---

## 1. Local Testing & Verification

To verify the implementation locally, run the following quality gates from the repository root:

### Automated Mock Contract Tests
Run the 7-test suite to verify the adapter's structural and behavioral contracts (gated by mock injection):
```bash
uv run pytest tests/channels/test_discord.py -v
```

### Live Integration Tests
To run live integration tests against the real Discord API (these auto-skip if credentials are not configured in your `.env`):
```bash
uv run pytest glc/channels/catalogue/discord/tests/test_live_discord.py -m requires_live_api -v
```


### Linter Compliance
Verify style rules and formatting guidelines are met:
```bash
uv run ruff check glc/channels/catalogue/discord/
```

### Static Type Checking
Verify type safety:
```bash
uv run mypy glc/channels/catalogue/discord/
```

---

## 2. Real-World Integration & Running the Bot

To test and run the adapter against the real Discord API end-to-end:

### Step A: Configure the Environment
Copy the environment template `glc/channels/catalogue/discord/env.example` to `.env` at the repository root and fill in your credentials:
```bash
cp glc/channels/catalogue/discord/env.example .env
```

Your `.env` should define:
* `DISCORD_BOT_TOKEN`: The bot token from the Discord Developer Portal.
* `DISCORD_TEST_CHANNEL_ID`: A channel ID where the bot has send/read permissions.
* `DISCORD_TEST_USER_ID` (optional): A user ID used to verify mention resolution.

### Step B: Start the GLC Gateway Server
Start the central GLC Gateway server on port `8111`:
```bash
uv run python -m glc.main
```

### Step C: Run the Discord WebSocket Bridge
Start the external bridge process to connect to the Discord API:
```bash
uv run python -m glc.channels.catalogue.discord.tests.run_discord_bridge
```

The bridge will automatically log into Discord, listen for incoming channel messages, forward them to your local gateway, and post agent echoes back to your Discord channel.

---

## 3. Direct Outbound Test
To test outgoing REST API messages directly without connecting the gateway:
```bash
uv run python -m glc.channels.catalogue.discord.tests.send_test_message
```
