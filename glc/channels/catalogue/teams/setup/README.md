# Teams adapter — local setup guide

End-to-end walkthrough: run the emulator stub, pair a trusted user, send a message, see the round-trip. No Azure tenant required for local testing.

```
Teams client (or curl / Emulator GUI)
    │  Activity JSON
    ▼
emulator_runner.py  (POST /api/messages on localhost:3978)
    │
    ├─ Adapter.on_message()  → classify trust → ChannelMessage
    └─ Adapter.send()        → echo reply Activity JSON
```

---

## Prerequisites

- Python 3.11+, `uv` installed
- `uv sync` from repo root
- (Optional) Bot Framework Emulator v4.15.1 for a GUI

---

## 1. Install Bot Framework Emulator (optional)

Download **v4.15.1** (last GA):

| OS | Installer |
|---|---|
| macOS | `BotFramework-Emulator-4.15.1-mac.dmg` |
| Windows | `BotFramework-Emulator-4.15.1-windows-setup.exe` |
| Linux | `botframework-emulator_4.15.1_amd64.deb` |

All three: [GitHub releases/tag/v4.15.1](https://github.com/microsoft/BotFramework-Emulator/releases/tag/v4.15.1).

Leave App ID / Password blank when connecting — anonymous mode bypasses Azure AD entirely. The demo works fully without Azure credentials.

> **M365 Developer Program note:** Microsoft closed free sign-ups in early 2024. Not needed — the emulator talks directly to `localhost:3978`, no cloud relay.

---

## 2. Start the stub server

```sh
# From repo root
uv run python -m glc.channels.catalogue.teams.setup.emulator_runner
```

Expected startup log:

```
INFO  Teams emulator stub → http://127.0.0.1:3978/api/messages  (--no-emulator=False)
```

For headless curl / CI (skips JWT auth check):

```sh
uv run python -m glc.channels.catalogue.teams.setup.emulator_runner --no-emulator
```

Flags:

| Flag | Default | Purpose |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `3978` | Bot Framework Emulator default |
| `--no-emulator` | off | Skip JWT auth — curl / CI |

---

## 3. Pair a trusted owner

Every inbound sender is classified via `classify("teams", from.id)`. An unpaired ID returns `trust_level == "untrusted"`. Pair before sending to see the full trust flow.

Teams `from.id` prefixes:
- `29:<oid>` — regular Teams user
- `8:orgid:<oid>` — org-scoped user
- `28:<app-id>` — bot (never pair a bot)

```sh
uv run python -m glc.channels.catalogue.teams.setup.trust_setup owner "29:42" --handle "demo-owner"
```

Expected output:

```
Paired '29:42' as owner_paired on channel 'teams'.
  29:42                    owner_paired   handle=demo-owner        paired_at=2026-07-03 12:00:00 UTC
```

### Demo all three trust levels

Find the Emulator's generated user ID in the server logs first:

```
INFO  round-trip OK  in='hello'  out={'type': 'message', 'text': '[echo] hello', ...}
```

Then set each trust level before sending a message:

```sh
# owner_paired — full trust
uv run python -m glc.channels.catalogue.teams.setup.trust_setup owner "29:42"

# user_paired — regular paired user
uv run python -m glc.channels.catalogue.teams.setup.trust_setup invite "29:42" --trust user_paired
uv run python -m glc.channels.catalogue.teams.setup.trust_setup confirm <code>

# untrusted — revoke to go back to default
uv run python -m glc.channels.catalogue.teams.setup.trust_setup revoke "29:42"
```

### All subcommands

```sh
uv run python -m glc.channels.catalogue.teams.setup.trust_setup owner "29:42" --handle alice
uv run python -m glc.channels.catalogue.teams.setup.trust_setup invite "29:99" --handle bob
uv run python -m glc.channels.catalogue.teams.setup.trust_setup confirm 042913
uv run python -m glc.channels.catalogue.teams.setup.trust_setup list
uv run python -m glc.channels.catalogue.teams.setup.trust_setup revoke "29:99"
uv run python -m glc.channels.catalogue.teams.setup.trust_setup revoke-all --yes
```

Pairings persist in `~/.glc/pairings.sqlite`. Override with `GLC_PAIRING_DB=<path>`.

---

## 4. Send a message and see the round-trip

### Option A — curl (headless)

Start with `--no-emulator`, then:

```sh
curl -s -X POST http://127.0.0.1:3978/api/messages \
  -H "Content-Type: application/json" \
  -d '{
    "type": "message",
    "id": "act-1",
    "timestamp": "2026-07-03T12:00:00.000Z",
    "channelId": "msteams",
    "serviceUrl": "https://smba.trafficmanager.net/amer/",
    "from": {"id": "29:42", "name": "demo-owner"},
    "conversation": {"isGroup": false, "id": "a:conv-1"},
    "recipient": {"id": "28:bot-id", "name": "GLC"},
    "text": "hello from curl"
  }' | python3 -m json.tool
```

Server log:

```
INFO  round-trip OK  in='hello from curl'  out={'type': 'message', 'text': '[echo] hello from curl', 'replyToId': 'act-1', 'textFormat': 'markdown'}
```

Response body (outbound Bot Framework Activity):

```json
{
  "type": "message",
  "text": "[echo] hello from curl",
  "replyToId": "act-1",
  "textFormat": "markdown"
}
```

### Option B — Bot Framework Emulator GUI

1. Open Emulator → **Open Bot**
2. **Bot URL**: `http://localhost:3978/api/messages` — leave App ID / Password blank
3. Click **Connect**
4. Type a message — response pane shows the outbound Activity JSON

Each step maps to adapter logic: type guard → trust classification → allowlist check → `ChannelMessage` → reply.

### Option C — Adaptive Card

```sh
curl -s -X POST http://127.0.0.1:3978/api/messages \
  -H "Content-Type: application/json" \
  -d '{
    "type": "message",
    "id": "act-2",
    "timestamp": "2026-07-03T12:00:00.000Z",
    "channelId": "msteams",
    "serviceUrl": "https://smba.trafficmanager.net/amer/",
    "from": {"id": "29:42", "name": "demo-owner"},
    "conversation": {"isGroup": false, "id": "a:conv-1"},
    "recipient": {"id": "28:bot-id", "name": "GLC"},
    "text": null,
    "attachments": [{
      "contentType": "application/vnd.microsoft.card.adaptive",
      "content": {
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [{"type": "TextBlock", "text": "Please review the doc.", "wrap": true}]
      }
    }]
  }' | python3 -m json.tool
```

The adapter walks the card body breadth-first, promotes the first `TextBlock` text to `ChannelMessage.text`, and stores the raw card under `metadata["adaptive_card"]`.

---

## 5. Run the test suite

```sh
uv run pytest tests/channels/test_teams.py -v
```

All 7 tests green. No credentials needed — tests use `TeamsMock`.

---

## 6. Azure Bot registration (production path)

For a live deployment against real Teams:

1. **Azure App Registration** — [portal.azure.com](https://portal.azure.com) → Azure Active Directory → App registrations. Note the **Application (client) ID** and create a client secret.
2. **Azure Bot resource** — create a Bot Channels Registration. Set messaging endpoint to `https://<your-host>/api/messages`.
3. **Teams channel** — enable it in the Azure Bot resource.
4. Set env vars:

```sh
export TEAMS_APP_ID="<app-id>"
export TEAMS_APP_PASSWORD="<client-secret>"
export TEAMS_TENANT_ID="<tenant-id>"
```

The adapter acquires OAuth client-credentials tokens from `login.microsoftonline.com/{TEAMS_TENANT_ID}/oauth2/v2.0/token` (scope `https://api.botframework.com/.default`) and caches them with a 60-second early-expiry guard. None of this runs in the local emulator path.

> **Single-tenant only:** Microsoft stopped new multi-tenant bot registrations after 2025-07-31. The adapter targets the single-tenant endpoint — do not change it to the deprecated `botframework.com` multi-tenant path.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `on_message → None` in server log | Activity `type` is not `"message"` | `conversationUpdate`, `typing`, etc. return `None` — expected |
| Response shows `trust_level == "untrusted"` | Sender ID not in pairing store | `trust_setup owner "<from.id>"` |
| `RuntimeError: no cached context for '<id>'` | `send()` before any `on_message()` for that user | Adapter caches `serviceUrl` on first inbound — send a message first |
| Port 3978 already in use | Another process | `--port 3979` (update Emulator Bot URL too) |
| `ModuleNotFoundError: No module named 'uvicorn'` | Deps not installed | `uv sync` from repo root |
| Emulator shows "Cannot connect" | Server not running or wrong URL | Server log must show `http://127.0.0.1:3978`; Emulator uses `http://localhost:3978/api/messages` |
