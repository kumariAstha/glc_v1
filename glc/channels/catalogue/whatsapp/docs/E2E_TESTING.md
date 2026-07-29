# E2E Testing — WhatsApp Adapter (US-13)

Companion to [`WEBHOOK_ARCHITECTURE_OPTIONS.md`](WEBHOOK_ARCHITECTURE_OPTIONS.md),
which defines three approaches to getting an inbound webhook to
`adapter.py`. This doc is the actual runbook for testing them — including
screenshots from the live run that produced two confirmed real round-trips
(Meta and Twilio) on 2026-07-01.

| Approach | Status here |
|---|---|
| **1 — Dev/POC** | Done in US-1 (`meta_webhook_test_server.py`), superseded — not re-tested here. |
| **2 — Our Demo Approach** | **Covered below in full, with screenshots.** This is what the US-13 demo video shows. |
| **3 — Standardized gateway route** | Parked in backlog. Placeholder at the end of this doc — not part of the US-1..15 submission. When picked up, it becomes its own separate PR to `theschoolofai/glc_v1:main` touching only `glc/routes/channels.py` (shared code, `@theschoolofai` review — see `WEBHOOK_ARCHITECTURE_OPTIONS.md`'s "Why this isn't done yet"). |

Automated regression coverage already exists and does **not** need to be
re-proven live: `tests/channels/test_whatsapp.py` (7 fixed Meta tests) and
`glc/channels/catalogue/whatsapp/tests/test_twilio_path.py` (31 self-built
Twilio tests) cover disconnect handling, tampered/unsigned signatures, the
429 rate-limit path, and the allowlist drop path. Run them with:

```bash
uv run pytest tests/channels/test_whatsapp.py glc/channels/catalogue/whatsapp/tests/ -v
```

E2E testing exists to prove the parts those suites structurally cannot:
that the wire actually reaches Meta/Twilio's real servers and a real
WhatsApp message round-trips end to end.

Screenshots referenced below live in
[`screenshots/e2e_testing/`](../assets/screenshots/e2e_testing/) alongside this doc, numbered to
match each step (`01_...png`, `02_...png`, ...).

---

## Approach 2 — Demo Webhook Server (live, both providers)

### What this proves

A real WhatsApp message, sent from your phone, is received by Meta or
Twilio, forwarded over a public tunnel to your machine, parsed and
trust-classified by `adapter.on_message()`, echoed back through
`adapter.send()`, and delivered back to your phone as a real WhatsApp
message — for **both** providers. This is the recording for `US-13`.

The GLC gateway (`glc/main.py`) is only needed for the **pairing**
handshake (`/v1/control/pair`); once paired, `demo_webhook_server.py`
talks to the adapter directly and the gateway's allowlist/rate-limit/audit
pipeline is bypassed (see `WEBHOOK_ARCHITECTURE_OPTIONS.md`'s note on this
— it's intentional and sufficient for the demo bar).

### What to have ready before you start

- [ ] `.env` populated for **both** providers — `WHATSAPP_PHONE_NUMBER_ID`,
      `WHATSAPP_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`,
      `WHATSAPP_WABA_ID`, `WHATSAPP_APP_ID`, `TWILIO_ACCOUNT_SID`,
      `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `TWILIO_WEBHOOK_URL`
      (this last one can't be filled in until step 7 below).
- [ ] Meta test number and app set up (`US-1` / `US1_meta_wiring_setup.md`)
      and reachable — the 24-hour messaging window opened at least once.
- [ ] Twilio sandbox joined from your personal phone (`join <code>`,
      `US-2` / `twilio_sandbox.md`) — remember the 3-day expiry.
- [ ] `ngrok` installed and on `PATH` (or another tunnel tool).
- [ ] `twilio` package importable — `uv run python -c "import twilio"`.
      Not yet in `pyproject.toml` (pending the separate shared-code PR,
      see `HANDOFF.md` §0.2); install manually into the venv until then.
- [ ] Screen/window recording ready to start before you send the first
      message, so both round-trips land in the same take.

### Two documentation bugs to know about before you pair

Found while preparing this runbook — `README.md`'s pairing steps
(§ Meta Step 13 / § Twilio Step 7) don't work exactly as written:

1. The `curl -X POST .../v1/control/pair` example has no request body.
   `PairRequest` (`glc/routes/control.py`) requires `channel` and
   `channel_user_id` in JSON — the bare curl 422s.
2. "Send the code as a WhatsApp message... the gateway will confirm
   pairing" doesn't happen automatically. Nothing in `channels.py`, the
   WS route, or the adapter watches inbound messages for a pending
   pairing code. Confirmation only happens through a manual
   `POST /v1/control/pair/confirm {"code": "..."}` call.

The corrected flow is below. (`README.md` itself still needs this fix —
tracked separately, not yet applied there.) Either `curl` or a REST client
like Postman works equally well — the screenshots below use Postman since
that's what was actually used for the reference run.

### Step-by-step

**Step 1 — start the gateway** (Terminal 1). Needed only for pairing —
pure localhost, no tunnel involved yet:
```bash
uv run glc serve
```
![glc serve](../assets/screenshots/e2e_testing/01_glc_serve.png)

**Step 2 — get your installation token** (same or a second terminal):
```bash
uv run glc token
```

**Step 3 — pair your phone as owner, part 1: request a code.** The
pairing DB is sqlite at `~/.glc/pairings.sqlite` and survives restarts,
so you only do this once per machine. This is a plain `localhost:8111`
call — Meta/Twilio are not involved in pairing at all, so no tunnel is
needed:
```bash
curl -X POST http://localhost:8111/v1/control/pair \
  -H "Authorization: Bearer <token-from-glc-token>" \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","channel_user_id":"91XXXXXXXXXX","user_handle":"owner","trust_level":"owner_paired"}'
```
`channel_user_id` is your own WhatsApp-registered number, E.164 digits,
no `+` (e.g. `91XXXXXXXXXX`) — the same format Meta/Twilio put in the
`from`/`WaId` field of any inbound webhook. Response looks like
`{"code":"186157","expires_at":...,"ttl_seconds":300}`.
![pair request/response](../assets/screenshots/e2e_testing/03_pair_request_response.png)

**Step 4 — pair your phone as owner, part 2: confirm the code**
(valid 5 minutes):
```bash
curl -X POST http://localhost:8111/v1/control/pair/confirm \
  -H "Authorization: Bearer <token-from-glc-token>" \
  -H "Content-Type: application/json" \
  -d '{"code":"186157"}'
```
This second call is what actually registers you as `owner_paired` — the
first call only issues the code.

**Step 5 — optional: verify the pairing landed in sqlite**, without
revealing your phone number:
```bash
python3 -c "
import sqlite3, os
p = os.path.expanduser('~/.glc/pairings.sqlite')
print('DB exists:', os.path.exists(p))
if os.path.exists(p):
    c = sqlite3.connect(p)
    rows = c.execute(\"SELECT channel, trust_level, paired_at, length(channel_user_id) FROM pairings WHERE channel='whatsapp'\").fetchall()
    print('whatsapp pairings (trust_level, paired_at, wa_id_len):', rows)
"
```
Expect `('whatsapp', 'owner_paired', <timestamp>, 12)`.

**Step 6 — stop the gateway, then start the demo server** (same terminal
or a fresh one — the two are mutually exclusive and both default to
port 8111, so only one can be bound at a time):
```bash
uv run python glc/channels/catalogue/whatsapp/demo_webhook_server.py
```
Listens on port **8111** — same as the gateway used for pairing above.

**Step 7 — reuse the same tunnel from pairing** (or start one if you
haven't yet):
```bash
ngrok http 8111
```
Since the demo server and the gateway share port 8111, the same ngrok
URL used for pairing keeps working here — no need to swap tunnels or
reconfigure the Meta/Twilio console between steps.

**Step 8 — register the same URL in both consoles.**
`demo_webhook_server.py` dispatches Meta vs. Twilio by which signature
header is present (`X-Hub-Signature-256` vs `X-Twilio-Signature`) — the
handler doesn't branch on URL path, so one ngrok URL serves both:

**8a — Meta** (2026 UI — the old "WhatsApp → Configuration → Webhook →
Edit" path referenced elsewhere no longer exists): **developers.facebook.com
→ My Apps → (your app) → Use cases (left sidebar) → Customize on
"Connect with customers through WhatsApp" → Step 2. Production setup →
Configure Webhooks**. Callback URL = the ngrok URL, Verify Token =
`WHATSAPP_VERIFY_TOKEN`. Click **Verify and Save**, then toggle
**Subscribe** on the **messages** row.
![Meta webhook config](../assets/screenshots/e2e_testing/08a_meta_webhook_config.png)

**8b — Twilio**: **Sandbox Settings → "When a message comes in"** → same
ngrok URL, Method = `POST` → **Save**.
![Twilio sandbox config](../assets/screenshots/e2e_testing/08b_twilio_sandbox_config.png)

Then set in `.env`:
```
TWILIO_WEBHOOK_URL=https://<your-ngrok-subdomain>.ngrok-free.app/
```

> **Confirmed gotcha (hit during our own live test):** Twilio signs its
> webhook using the URL **with a trailing slash** even when the console
> field is saved without one (`POST / HTTP/1.1` is the actual request
> line it sends). If `TWILIO_WEBHOOK_URL` in `.env` has no trailing
> slash, every signature check fails — confirmed by capturing a real
> request via ngrok's own inspector (`http://127.0.0.1:4040`) and
> recomputing the signature both ways; only the trailing-slash form
> matched. **Always add the trailing `/`**, regardless of what the
> console field displays, and restart `demo_webhook_server.py` after
> editing `.env` (it loads `.env` once at startup).

**Step 9 — find your Meta test number and unlock the messaging window.**
Left sidebar → **Basic setup → Step 1. Try it out**. The **From** field
shows your Meta-provided test number, tied to `WHATSAPP_PHONE_NUMBER_ID`.
Your own personal number needs to be listed as a test recipient there —
if this is the first time, click **Send** to fire the pre-filled
`hello_world` template to yourself once (Meta requires this before a
fresh test number can exchange free-form messages with you), then reply
to it from your phone.

**Step 10 — Meta round-trip.** Text your Meta test number (or reply to
the `hello_world` template). Expect in the demo server terminal:
```
[demo] inbound provider=meta from=<wa_id> trust=owner_paired text='...'
[demo] send() result: {'messaging_product': 'whatsapp', ...}
```
and a reply `[glc echo] ...` on your phone.
![Meta round-trip on phone](../assets/screenshots/e2e_testing/10_meta_roundtrip_phone.png)

**Step 11 — Twilio round-trip.** Text the Twilio sandbox number. Expect:
```
[demo] inbound provider=twilio from=<wa_id> trust=owner_paired text='...'
[demo] send() result: {'sid': ..., 'status': 'queued', ...}
```
and a reply on your phone via the sandbox number. (If you hit
`bad Twilio signature` here, see the trailing-slash gotcha in step 8b.)
![Twilio round-trip terminal](../assets/screenshots/e2e_testing/11_twilio_roundtrip_terminal.png)

Record both. That's the two real round-trips `US-13` needs. **Confirmed
working end to end for both providers** on this fork (2026-07-01).

### Optional: prove the untrusted path live too

Have a second phone (or ask a friend) text the same numbers without
pairing. Expect `trust=untrusted` in the log and, since
`channels.yaml` currently has `whatsapp: {enabled: false}`, the DM-mode
bypass in `adapter.py`'s `on_message()` still lets it through as an
untrusted `ChannelMessage` — but `send()`'s pairing guard blocks any
reply with `{"error": "recipient not paired", "code": "outbound_blocked"}`.
Not required for the demo video; useful if you want the recording to show
the security boundary as well as the happy path.

### Troubleshooting

Provider-specific issues (expired token, expired sandbox join, signature
mismatch) are already covered in `README.md`'s
[Troubleshooting](../README.md#troubleshooting) table — check there
first. E2E-specific ones:

| Symptom | Cause | Fix |
|---|---|---|
| `outbound_blocked` on first message | Expected — you haven't paired yet | Run the pair + pair/confirm calls above, then resend |
| Nothing prints in the demo server terminal at all | the demo server isn't actually running, or the gateway is still holding port 8111 | `demo_webhook_server.py` listens on **8111** (`WEBHOOK_PORT`) — same port as the gateway. Stop `glc serve` before starting the demo server; both can't bind 8111 at once. |
| 422 from `/v1/control/pair` | Missing JSON body (bug #1 above) | Use the corrected curl with `-d` and `Content-Type: application/json` |
| Paired but still `trust=untrusted` | Wrong `channel_user_id` format | Must be bare digits, no `+`, no `whatsapp:` prefix — matches the `WaId`/`from` field exactly |
| `[demo] dropped: bad Twilio signature ...` | `TWILIO_WEBHOOK_URL` missing the trailing slash Twilio actually signs with | Add the trailing `/` (see step 8b), restart the demo server, resend |
| `[demo] dropped: verified Meta status callback ...` (repeated 2-3x per message) | Normal — Meta sends separate sent/delivered/read receipt webhooks for every message, which correctly have no `messages` key | Not an error, no action needed (see `HANDOFF.md` §7.4) |

**Note on ports:** pairing happens through the gateway on **8111**;
message delivery happens through the demo server, also on **8111**
by default. They're mutually exclusive — stop the gateway before
starting the demo server. Because both use the same port, the same
ngrok tunnel and the same Meta/Twilio console URL stay valid across
both steps; no reconfiguration needed when switching between them.

---

## Approach 3 — Standardized Gateway Route (backlog placeholder)

**Status: parked.** Not attempted as part of `US-1` through `US-15`. See
`WEBHOOK_ARCHITECTURE_OPTIONS.md`'s Approach 3 section for the exact
routes (`GET`/`POST /v1/channels/{name}/webhook`) that would need to be
added to `glc/routes/channels.py`.

When this is picked back up, it ships as its own PR:

- **Scope:** `glc/routes/channels.py` only — shared code, outside every
  group's owned path.
- **Process:** separate PR to `theschoolofai/glc_v1:main`, no `# Group:`
  marker (the boundary check's documented bypass — see
  `GROUPS.md`'s shared-code exception, quoted in `HANDOFF.md` §0.1),
  under `@theschoolofai` review.
- **Payoff once merged:** single-process startup (`uv run python
  glc/main.py`, no separate demo server, no manual 3-terminal dance),
  the real allowlist/rate-limit/audit pipeline exercised instead of
  bypassed, and the same route works for all 15 channels, not just ours.
- **This section will be filled in with an actual test runbook** once
  that PR is drafted and the route exists to test against.
