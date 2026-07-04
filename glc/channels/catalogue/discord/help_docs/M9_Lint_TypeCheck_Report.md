# M9 — Linter & Type Annotation Compliance Report

**Task:** Ensure ruff and mypy compliance for all files under glc/channels/catalogue/discord/
**Result:** All checks pass — ruff check, ruff format, mypy — zero errors

## Issues Found & Fixed (all in adapter.py)

### 1. I001 — Import block unsorted
Reordered first-party imports alphabetically. `catalogue.discord.schemas` now sorts before `envelope`.

### 2. UP017 — Use datetime.UTC alias
Replaced legacy `timezone.utc` with Python 3.11+ `UTC` constant from the datetime module.

### 3. Trailing blank line at EOF
Removed extra blank line after `_parse_ts` function to satisfy ruff format.

## Validation

- `ruff check glc/channels/catalogue/discord/` → All checks passed
- `ruff format --check glc/channels/catalogue/discord/` → 8 files already formatted
- `mypy glc/channels/catalogue/discord/` → Success: no issues found in 8 source files
- `pytest tests/channels/test_discord.py -v` → 7 passed

## schemas.py & __init__.py
No changes needed — already had from __future__ import annotations, clean type hints, and no lint violations.
