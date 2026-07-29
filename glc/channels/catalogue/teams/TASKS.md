# Group 15 — Teams adapter task distribution

> Companion to [`ARCHITECTURE.md`](ARCHITECTURE.md). The architecture
> doc covers what we're building; this doc covers who builds what,
> when, and how we coordinate.

## Context

### Where we are

Microsoft Teams (slot `teams`) is Group 15's S11 channel-adapter assignment.

A prior team's PR was merged on 2026-06-29 and then reverted by the
instructor a few hours later via PR #24 (commit `daa32ba`), with the
message "give Group 15 a clean slate." The Teams adapter on
`origin/main` is back to the scaffold stub. The seven tests at
`tests/channels/test_teams.py` and the mock at
`tests/channels/mocks/teams_mock.py` were not touched by the revert —
the contract surface is stable.

Deadline: **Mon Jul 6 09:00 IST**.

### Constraints

| Constraint | Source | What it means |
|---|---|---|
| Communication only in axiom chat | Instructor's pinned rule | No Telegram, no WhatsApp, no Google Meet (unless results posted back to chat). Silence = score 0 |
| Every member needs ≥1 meaningful commit | Instructor's grading rule | Members without a commit get 0 individually, even if the team's PR is perfect |
| Single PR per group to upstream | `docs/ADAPTER_GUIDE.md` | We open ONE upstream PR from `teams-adapter-g15` → `theschoolofai:main` |
| Boundary check enforced | `scripts/check_pr_boundaries.py` | Diffs must stay inside `glc/channels/catalogue/teams/` |
| Tests + mocks are scaffold-locked | `glc/channels/catalogue/teams/README.md` | Do NOT edit `tests/channels/test_teams.py` or `tests/channels/mocks/teams_mock.py` |

### How we work

```
Team members → individual feature branches → PRs into teams-adapter-g15 → merge
   accumulates contributions
                                                         │
                                                         ▼
                                            ONE upstream PR
                                            teams-adapter-g15 → theschoolofai:main
                                                         │
                                                         ▼
                                            CI scorecard runs, TA reviews,
                                            Rohan merges (Jul 3-5 window)
```

## Carve-outs (10 total)

Each carve-out is a real, gradeable commit. One per member. Claim by
replying in axiom Group 15 chat with the letter (e.g. *"Claiming A"*).
First-come first-served. If you want to pair on one, say so in the
claim message.

| Letter | Task | Hours | Status | Owner | Branch (when claimed) |
|--:|---|--:|---|---|---|
| **A** | Core `adapter.py` + `schemas.py` — `on_message` + `send`; all 7 tests pass | 6–8 | ✅ done | Swapnil Gusani | `swapniel/teams-adapter` |
| **B** | `ARCHITECTURE.md` § Adaptive Card BFS — done as part of PR #1 | 2–3 | ✅ done | Abhinav Rana | `abhinav/teams-architecture-doc` |
| **C** | `setup/emulator_runner.py` + `setup/__init__.py` — local stub server for the demo | 4–6 | ✅ done | Swapnil Gusani | `swapniel/teams-emulator-runner` |
| **D** | `setup/trust_setup.py` — CLI to pair/unpair/list trusted users | 3–4 | ✅ done | Abhinav Rana | `abhinav/teams-trust-setup` |
| **E** | `setup/README.md` — Bot Framework Emulator + Azure setup walkthrough | 3–4 | ✅ done | Swapnil Gusani | `swapnil/teams-setup-readme` |
| **F** | `ARCHITECTURE.md` § wire-format quirks table — done as part of PR #1 | 2–3 | ✅ done | Abhinav Rana | `abhinav/teams-architecture-doc` |
| **G** | `ARCHITECTURE.md` § Mermaid sequence diagram — done as part of PR #1 | 2 | ✅ done | Abhinav Rana | `abhinav/teams-architecture-doc` |
| **H** | Demo video (Loom unlisted, ~5 min) — `pytest` green + emulator round-trip | 2–3 | ✅ done | Raghav | (no branch; URL posted in upstream PR body) |
| **I** | PR review + lint polish — ruff/mypy/boundary check green before upstream PR opens | 2–3 | ✅ done | Swapnil Gusani | `swapniel/teams-lint-polish` |
| **J** | CI scorecard pre-flight — run all checks locally, post scorecard screenshot in axiom chat before opening upstream PR | 1–2 | ✅ done | Swapnil Gusani | (no branch; verification only) |

### Carve-out details

#### A — Core adapter
The biggest carve-out. Writes `Adapter.on_message` and `Adapter.send`.
Needs ~120-180 lines including helpers (`_extract_card_text` BFS walk,
`_strip_mentions`, `_cache_conversation`). Reference: §3 of
`ARCHITECTURE.md` for what each branch does. Success criterion:
`uv run pytest tests/channels/test_teams.py -v` shows all 7 green,
`ruff check` and `mypy` clean. Needs a Tuesday-morning starter who
can commit 6-8 focused hours.

#### C — Emulator runner
A tiny aiohttp server exposing `POST /api/messages` that wraps the
adapter and lets curl or the Bot Framework Emulator drive it. Used
for the demo. Includes a `--no-emulator` flag for headless testing.
Success criterion: `python -m glc.channels.catalogue.teams.setup.emulator_runner`
starts a server that accepts a POST with sample Activity JSON and
returns 200 with the adapter's outbound payload as the response body.

#### D — Trust setup CLI
Subcommands: `pair <aad_id>`, `unpair <aad_id>`, `list`, `revoke-all`.
Writes to the framework's `get_pairing_store()` so the adapter sees
trusted users at runtime. Success criterion: all four subcommands work
end-to-end against the real pairing store on the author's machine.

#### E — Setup README
The setup walkthrough. Sections: install Bot Framework Emulator
v4.15.1 (last GA), run `emulator_runner.py`, pair an owner with
`trust_setup.py`, Azure Bot registration path (with the M365
Developer Program closure caveat), troubleshooting. Success criterion:
verified by another team member doing a cold run.

#### H — Demo video
Loom unlisted, ~5 minutes. Walks: clone → `pytest` green → start
emulator → pair owner → send a card → show adapter response in logs.
Needs A + C + D done first. Posted as URL in the upstream PR body.

#### I — PR review + lint polish
Read the diff, run `ruff check`, `ruff format --check`, `mypy`, and
the boundary check. Submit at least one substantive review comment.
Push any cleanup commits. Success criterion: all CI checks green
before the upstream PR is moved from draft to ready-for-review.

#### J — Scorecard pre-flight
Run the full local test suite + lint + boundary check + mypy and
post a screenshot of the green output in the axiom chat just before
the upstream PR is opened. Catches "passes on my machine" failures
before they hit CI.

## Timeline

| Day | Date | Goal |
|---|---|---|
| **Mon** | Jun 29 | Carve-outs posted (this doc). Team claims start. |
| **Tue** | Jun 30 | All carve-outs claimed by EOD. Each claimant posts a 1-line progress update. |
| **Wed** | Jul 1 | A opens draft PR with `adapter.py` + `schemas.py` and all 7 tests passing. C, D, E start their setup work. |
| **Thu** | Jul 2 | C, D, E land their PRs onto `teams-adapter-g15`. I runs lint polish. J runs pre-flight. PR moves from draft to ready-for-review. |
| **Fri** | Jul 3 | H posts Loom demo URL in upstream PR body. TA review window opens. |
| **Sat** | Jul 4 | Address any TA feedback. Each member confirms their commit is in the PR. |
| **Sun** | Jul 5 | PR merged. Every member submits PR URL + Loom URL to the LMS individually. |
| **Mon** | Jul 6 09:00 IST | Deadline. We are done by Sunday EOD; Monday is safety margin. |

**Critical path:** A → I → J → upstream PR merge. If A slips a day,
the whole timeline slips. Whoever claims A should be able to commit
6-8 focused hours on Tuesday.

## Communication cadence

All posts go in the **official axiom Group 15 chat** (not Telegram,
not WhatsApp). The instructor's pinned rule applies: silence = score 0.

| When | What to post | Length |
|---|---|---|
| **Today** | Claim your carve-out: *"Claiming X"* | 1 line |
| **Tue Jun 30 EOD** | Progress update: what's done, what's next, blockers | 1-2 sentences |
| **Wed Jul 1** | When you push your feature branch, post the PR URL | 1 line |
| **Thu Jul 2** | When your PR merges into `teams-adapter-g15`, confirm | 1 line |
| **Fri Jul 3** | Demo URL when H posts it | (already in PR) |
| **Sat Jul 4** | Confirm your commit is in the upstream PR | 1 line |
| **Sun Jul 5** | LMS submission confirmation | 1 line |

If you're blocked >4 hours, tag the team in chat. Don't sit on it
overnight.

## Branch convention

| Branch | Purpose |
|---|---|
| `teams-adapter-g15` | The team's working branch on `levelscorner/glc_v1` (this fork). Open PRs against it. |
| `<your-name>/<what>` | Your feature branch (e.g. `abhinav/teams-architecture-doc`). Branch off `teams-adapter-g15`, work, push to fork, open PR into `teams-adapter-g15`. |
| One upstream PR | `levelscorner:teams-adapter-g15` → `theschoolofai:main`. Opened once when the team branch is ready. |

## Owned path (boundary check)

Everything you commit must live under:

```
glc/channels/catalogue/teams/
glc/channels/catalogue/teams/**
```

If your diff touches anything outside this path, the boundary check
fails and CI rejects the PR. Tests and mocks are off-limits.

Verify locally before opening a PR:

```bash
uv run python scripts/check_pr_boundaries.py \
    --base origin/main --head HEAD --group Teams
```

Expected output: `[boundary] OK: N file(s) changed, all inside 'Teams' owned paths`.

## What's already done (PR #1 on this fork)

| Item | File | PR |
|---|---|---|
| Architecture text-art + Mermaid sequence diagram | `ARCHITECTURE.md` | [#1](https://github.com/levelscorner/glc_v1/pull/1) |
| 9 wire-format quirks table | `ARCHITECTURE.md` | [#1](https://github.com/levelscorner/glc_v1/pull/1) |
| Adaptive Card BFS body extraction explained | `ARCHITECTURE.md` | [#1](https://github.com/levelscorner/glc_v1/pull/1) |
| Trust posture + allowlist gating | `ARCHITECTURE.md` | [#1](https://github.com/levelscorner/glc_v1/pull/1) |
| Field-by-field mapping table | `ARCHITECTURE.md` | [#1](https://github.com/levelscorner/glc_v1/pull/1) |
| 7 tests mapped to architecture steps | `ARCHITECTURE.md` | [#1](https://github.com/levelscorner/glc_v1/pull/1) |
| Microsoft Learn references | `ARCHITECTURE.md` | [#1](https://github.com/levelscorner/glc_v1/pull/1) |

That covers carve-outs **B**, **F**, and **G**. Once PR #1 merges,
the file is on `teams-adapter-g15` for everyone to read.

## What's NOT done yet

| Item | Owner | Notes |
|---|---|---|
| `adapter.py` implementation | A (unclaimed) | The core work |
| `schemas.py` (likely empty or minimal) | A (unclaimed) | Bundled with A |
| `setup/__init__.py` | C (unclaimed) | One-line file |
| `setup/emulator_runner.py` | C (unclaimed) | Local stub server |
| `setup/trust_setup.py` | D (unclaimed) | Pairing CLI |
| `setup/README.md` | E (unclaimed) | Setup walkthrough |
| Demo video | H (unclaimed) | Loom URL |
| Lint polish | I (unclaimed) | Final cleanup |
| Scorecard pre-flight | J (unclaimed) | Verification |
| Upstream PR opened | After all the above | One PR to `theschoolofai/glc_v1:main` |

## How to claim and contribute

1. Pick a letter (A, C, D, E, H, I, or J) from the unclaimed list above.
2. Reply in axiom Group 15 chat: *"Claiming X — will start [day]."*
3. Branch off `teams-adapter-g15` on this fork (`levelscorner/glc_v1`):
   ```bash
   git fetch fork
   git checkout -b your-name/teams-<task> fork/teams-adapter-g15
   ```
4. Make commits.
5. Push to your own fork of `levelscorner/glc_v1`, OR if you have write access here, push directly to a branch on this fork.
6. Open a PR with base = `teams-adapter-g15`.
7. Post the PR URL in axiom chat.
8. Once reviewed and merged, your commit is on `teams-adapter-g15` and will flow into the upstream PR when we open it.

## References

- Architecture and contract: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Assignment brief (scaffold): [`README.md`](README.md)
- Adapter discipline rules: [`docs/ADAPTER_GUIDE.md`](../../../../docs/ADAPTER_GUIDE.md)
- Test file (scaffold-locked): [`tests/channels/test_teams.py`](../../../../tests/channels/test_teams.py)
- Mock (scaffold-locked): [`tests/channels/mocks/teams_mock.py`](../../../../tests/channels/mocks/teams_mock.py)
- Owned-path enforcement: [`scripts/check_pr_boundaries.py`](../../../../scripts/check_pr_boundaries.py)
