# Investment Journal And AI Opinion Stage 1

This document captures the first migration slice of the InvestmentOS AI Opinion feature into DSA.

## Scope

Stage 1 only delivers the backend contract and data loop.

- `ai_opinions` is now a versioned table bound to one non-null `analysis_history_id`.
- `investment_journal_entries` is now the per-stock timeline table keyed by `stock_code + market`.
- Automatic analysis journal entries are created idempotently from a single-stock `analysis_history`.
- Manual investment notes preserve `raw_content` separately from `structured_output_json`.
- Stage 1 does not call LLMs, does not migrate Xueqiu data, and does not add K5 review logic.

## API

- `GET /api/v1/investment-journals`
  - Query one stock timeline by required `stock_code`, `market`, optional `entry_type`, `page`, `page_size`.
- `GET /api/v1/investment-journals/{entry_id}`
  - Read one journal entry.
- `POST /api/v1/investment-journals/manual`
  - Create one manual investment note.
- `PATCH /api/v1/investment-journals/manual/{entry_id}`
  - Update one manual investment note only; automatic analysis entries return a conflict error.
- `POST /api/v1/investment-journals/sync-analysis/{analysis_history_id}`
  - Idempotently create the automatic analysis entry for one `analysis_history`.
- `GET /api/v1/ai-opinions`
  - List AI opinions for one `analysis_history_id`.
- `GET /api/v1/ai-opinions/{opinion_id}`
  - Read one AI opinion version.

Phase 1 intentionally does not expose a public AI Opinion write API. Version creation stays in the service/repository layer until the generation flow is introduced in a later phase.

## Data Notes

- Automatic journal entries use unique `source_analysis_history_id` for idempotency.
- Recreating an AI opinion for the same `analysis_history` increments `version` and flips the prior current version to `is_current=false` inside one write transaction.
- SQLite also keeps a partial unique index so one `analysis_history` can have at most one `is_current=true`.
- `analysis_history` deletion removes linked `ai_opinions`, but preserves automatic `investment_journal_entries` as snapshots.
- Preserved analysis journal snapshots clear `source_analysis_history_id`, keep the original summary/risk/watch fields, and expose `source_status=deleted` plus `analysis_history_available=false`.
- Pipeline journal sync is best-effort after `analysis_history` is already saved; sync failures are logged and can be recovered later through `POST /api/v1/investment-journals/sync-analysis/{analysis_history_id}`.

## Snapshot Extraction And Time Semantics

- `summary_snapshot` prefers `analysis_history.analysis_summary`, then falls back to `raw_result.analysis_summary`.
- `risk_summary` is extracted from `raw_result.risk_summary`, then `risk`, then `risks`.
- `watch_items_json` stores a JSON array distilled from `watch_items`, `watch_points`, `attention_points`, `risks`, and `risk_factors`, capped to 10 items.
- Manual `raw_content` max length is 20000 characters; `summary_snapshot` max length is 4000.
- New tables follow the existing DSA convention of UTC naive datetimes via `utc_naive_now()`, and list ordering is `created_at DESC, id DESC`.

## Database Initialization And Incremental Compatibility

- `Base.metadata.create_all()` creates the stage-1 tables for fresh databases.
- SQLite connections explicitly enable `PRAGMA foreign_keys=ON`.
- Existing SQLite databases are incrementally upgraded at startup:
  - `investment_journal_entries.source_status` is added and backfilled.
  - the partial unique index `uix_ai_opinion_current_per_analysis` is created if missing.
  - legacy duplicate `is_current=true` rows are converged to the highest `(version, id)` before the unique index is created.
- `delete_analysis_history_records()` clears journal source references and marks snapshots deleted in the same delete transaction before the source `analysis_history` rows are removed.
- The delete flow explicitly flushes journal reference updates before deleting `analysis_history`, so foreign-key enforcement does not race against ORM dirty state.

## Real Verification Environment

- Repository support statement: Python 3.10+ (`README.md`, deployment docs).
- CI runtime: Python 3.11 (`.github/workflows/ci.yml`).
- Local verification runtime used for this stage-1 validation: `.venv-codex` created with Python 3.12.13, which is still within the repository's declared supported range.
- Dependency install entry used: `.\.venv-codex\Scripts\python.exe -m pip install -r .github/requirements-ci.txt`
- Direct SQLite probe result in the restored environment: `sqlite_version=3.50.4`, `foreign_keys=1`.

## Real Commands Executed

- Environment checks
  - `.\.venv-codex\Scripts\python.exe --version`
  - `.\.venv-codex\Scripts\python.exe -c "import sqlalchemy, pydantic, fastapi, numpy, pandas"`
  - `.\.venv-codex\Scripts\python.exe -c "import src.storage"`
  - `.\.venv-codex\Scripts\python.exe -c "import api.v1.router"`
- Stage-1 module tests
  - `.\.venv-codex\Scripts\python.exe -m pytest tests/test_investment_journal_service.py -q`
  - `.\.venv-codex\Scripts\python.exe -m pytest tests/test_ai_opinion_service.py -q`
  - `.\.venv-codex\Scripts\python.exe -m pytest tests/test_investment_journal_storage_migration.py -q`
  - `.\.venv-codex\Scripts\python.exe -m pytest tests/test_pipeline_investment_journal_sync.py -q`
  - `.\.venv-codex\Scripts\python.exe -m pytest tests/test_ai_opinion_and_journal_api.py -q`
- Related regression checks
  - `.\.venv-codex\Scripts\python.exe -m pytest tests/test_analysis_history.py -q`
  - `.\.venv-codex\Scripts\python.exe -m pytest tests/test_decision_signal_api.py -k stock_filter_codes -q`
  - `.\.venv-codex\Scripts\python.exe -m pytest tests/test_config_validate_structured.py -q`
- Official gate equivalence on Windows
  - syntax: equivalent `py_compile` file list from `scripts/ci_gate.sh`
  - flake8: `.\.venv-codex\Scripts\flake8.exe . --count --select=E9,F63,F7,F82 --show-source --statistics`
  - deterministic checks: PowerShell-equivalent execution of the `scripts/test.sh code` and `scripts/test.sh yfinance` logic
  - offline suite: `.\.venv-codex\Scripts\python.exe -m pytest -m "not network"`

## Verification Results

### Passed

- environment import checks for `sqlalchemy`, `pydantic`, `fastapi`, `numpy`, `pandas`
- `src.storage` import
- `api.v1.router` import
- stage-1 module tests listed above
- `tests/test_analysis_history.py`
- stock-code normalization regressions in `tests/test_decision_signal_api.py -k stock_filter_codes`
- `tests/test_config_validate_structured.py`
- deterministic code/yfinance checks equivalent to `scripts/test.sh`
- SQLite runtime verification for:
  - `PRAGMA foreign_keys=ON`
  - AI opinion current-version partial unique index creation
  - analysis-history delete path preserving journal snapshots and deleting linked AI opinions

### Not passed / not repository-wide clean yet

- repository-wide flake8 critical gate currently fails because 13 other dirty test files in the current worktree contain syntax or UTF-8 corruption:
  - `tests/test_agent_chat_api.py`
  - `tests/test_agent_executor.py`
  - `tests/test_alphasift_api.py`
  - `tests/test_chat_context.py`
  - `tests/test_llm_usage.py`
  - `tests/test_market_analyzer_generate_text.py`
  - `tests/test_multi_agent.py`
  - `tests/test_pipeline_notification_image_routing.py`
  - `tests/test_run_diagnostics_p1.py`
  - `tests/test_run_diagnostics_p2.py`
  - `tests/test_run_flow.py`
  - `tests/test_signal_attribution_supplement.py`
  - `tests/test_storage.py`
- the official offline suite `pytest -m "not network"` is blocked at collection by the same 13 files.
- these blockers are outside the stage-1 file set for AI Opinion / Investment Journal and were confirmed by current worktree diff plus `git blame` on the broken lines to be separate uncommitted edits, not failures introduced by the stage-1 module itself.

## Current Acceptance Status

- Stage-1 code paths added for investment journals and AI opinions have been validated in a reproducible local environment.
- The remaining repository-wide gate failures are real, but they come from unrelated dirty test files outside this module.
- On the stage-1 module boundary, acceptance is satisfied and phase 2 can start only after an explicit product decision to move on; this document does not claim repository-wide clean-room verification.
