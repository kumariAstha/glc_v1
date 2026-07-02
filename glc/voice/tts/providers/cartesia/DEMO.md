# Cartesia Sonic TTS — Demo

**Video (real upstream call, end to end):** https://youtu.be/mcZpQq33gww

This adapter turns text into speech using Cartesia's Sonic model. The
CI tests run against a mock; this demo proves the **real** wire path to
`api.cartesia.ai` works end to end — text in, playable WAV out through
the gateway.

## What the demo shows

1. All 7 provider tests passing against the mock.
2. `ruff` and `mypy` clean on the owned path.
3. A **real** call to Cartesia's live API through `POST /v1/speak`,
   returning WAV audio that is then played out loud.

## Reproduce it

### 1. Get a Cartesia API key

Free tier at https://play.cartesia.ai/keys — the key starts with `sk_car_`.

### 2. Run the checks

```sh
uv sync --dev

# 7 provider tests (mock, no network)
uv run pytest tests/voice/tts/test_cartesia.py -v

# lint + types on the owned path
uv run ruff check glc/voice/tts/providers/cartesia/
uv run mypy      glc/voice/tts/providers/cartesia/
```

### 3. Real upstream call through the gateway

The gateway must see the key in its environment. Export it in the same
shell that starts the server:

```sh
# Terminal 1 — start the gateway
export CARTESIA_API_KEY=sk_car_...
uv run glc serve            # boots on http://localhost:8111

# Terminal 2 — send text, get real audio back
curl -X POST http://localhost:8111/v1/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from Cartesia Sonic", "prefer": "streaming"}' \
  | python3 -c "import sys,json,base64; open('out.wav','wb').write(base64.b64decode(json.load(sys.stdin)['audio_b64']))"

afplay out.wav             # macOS — play the generated speech
```

A successful call returns `provider: cartesia`, `mime: audio/wav`,
`sample_rate: 24000`, and a base64 WAV payload.

## Wire-format quirks

- **Auth header is `X-API-Key`**, not `Authorization: Bearer`.
- At the pinned API version (`2025-04-16`), Cartesia's error responses
  are **plain text** (`Title: Message`), not JSON — the adapter parses
  them accordingly.
- Model `sonic-2`, output WAV / 16-bit PCM / 24 kHz mono.
