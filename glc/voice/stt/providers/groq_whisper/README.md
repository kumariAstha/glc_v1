# Groq Whisper Large v3 Turbo STT Provider

This provider implements Speech-to-Text (STT) transcription via the Groq Cloud LPU platform, using the `whisper-large-v3-turbo` model to achieve sub-second transcription latencies.

## Status

**Fully Implemented & Verified**. All structural, behavioural, and routing integration tests pass successfully.

---

## Modular Architecture

The adapter uses a highly modular structure. The main provider orchestrates logical steps isolated in separate helper modules:

* **`adapter.py`**: High-level orchestrator executing validation, configuration, payload building, network dispatch, response parsing, and translation.
* **`schemas.py`**: Defines Pydantic models for response mapping (`GroqVerboseJsonResponse` and `GroqSegment`).
* **`validation.py`**: Validates input types and values.
* **`config.py`**: Loads API configurations and model overrides from the environment.
* **`payload.py`**: Maps MIME formats and constructs multipart payloads.
* **`network.py`**: Manages asynchronous HTTP requests to `api.groq.com`.
* **`parsing.py`**: Handles JSON loading and Pydantic validation.
* **`conversion.py`**: Maps parameters to a canonical `TranscribeResult`.

---

## Configuration

Required environment variables:

* **`GROQ_API_KEY`**: Your Groq API credentials.

Optional environment variables:

* **`GLC_GROQ_STT_MODEL`**: Override the target model (defaults to `whisper-large-v3-turbo`).

---

## Testing

### Automated Test Suite
To verify that all adapter features work correctly, run the test suites:
```sh
# Run main provider tests
uv run pytest tests/voice/stt/test_groq_whisper.py

# Run voice routing tests
uv run pytest tests/test_voice_routing.py

# Run transcription endpoint tests
uv run pytest tests/test_transcribe_route.py
```

### Interactive Microphone Recording
To test with a live laptop recording, use the helper script created at the workspace root:
```sh
uv run test_stt_mic.py
```

---

## Verification & Test Results

All 23 automated tests pass successfully:

### 1. Provider Adapter Tests
```
(base) C:\SchoolofAI\session11> uv run pytest tests/voice/stt/test_groq_whisper.py
collected 7 items

tests\voice\stt\test_groq_whisper.py .......                             [100%]

============================== 7 passed in 0.29s ==============================
```

### 2. Voice Routing Layer Tests
```
(base) C:\SchoolofAI\session11> uv run pytest tests/test_voice_routing.py
collected 12 items

tests\test_voice_routing.py ............                                 [100%]

============================= 12 passed in 3.79s ==============================
```

### 3. FastAPI Endpoint Transcription Tests
```
(base) C:\SchoolofAI\session11> uv run pytest tests/test_transcribe_route.py
collected 5 items

tests\test_transcribe_route.py .....                                     [100%]

======================== 5 passed, 1 warning in 0.38s =========================
```
