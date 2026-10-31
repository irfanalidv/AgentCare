# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and this project follows Semantic Versioning.

## [0.3.1] - 2026-10-31

### Fixed

- **Local data loss.** The JSON stores (customers, call events, lifecycle events, wellness
  history, processed executions, sync state) treated an unreadable file as empty and overwrote it
  on the next write. A corrupt file is now moved aside as `<name>.corrupt-<timestamp>` with a
  warning, and all writes are atomic (temp file + rename).
- **Email HTML injection.** Transcript- and LLM-derived fields (name, reason, summary, doctor) are
  HTML-escaped in confirmation emails.
- **Bolna sync** no longer marks in-progress executions as automated, which had prevented booking
  automation from ever running for them once they completed.
- **Secret redaction.** The Cal.com error redaction regex missed `apiKey` values containing the
  letter "s"; booking exceptions are now redacted as well.
- **CLI JSON output** is plain stdout instead of `rich.print`, which wrapped long lines inside JSON
  strings and interpreted `[...]` as markup.
- Postgres connections always use a connect timeout; `MistralLLM` sets a 30 s request timeout
  (the SDK default is unbounded).
- Extraction, policy-file, doctor-schema and summary-polish failures are logged instead of being
  silently swallowed.
- `assign_doctor(doctors=[])` now honours the empty directory instead of loading the defaults.
- mypy findings: None-unsafe email comparison in the JSON customer store, untyped
  metadata/context handling in `resolve_execution_workflow`.

### Added

- `MistralLLM(timeout_s=...)`.
- Examples (all offline): `frontdesk_offline_pipeline.py`, `wellness_trend_monitoring.py`,
  `fhir_booking_local_server.py`, `transcript_triage_batch.py`.
- CI: mypy, coverage gate (75%), concurrency; CodeQL workflow; pre-commit config.

### Changed

- Ruff rule set broadened (SIM, C4, RUF, PTH, RET, PIE); `[tool.mypy]` config; test coverage
  38% -> 79% (113 tests, all offline).
- README rewritten (architecture diagram, configuration incl. FHIR settings, API overview,
  references).

## [0.3.0] - 2026-10-31

### Added

- `agentcare --version`.
- `py.typed` marker (`Typing :: Typed`).
- Tests for `MistralLLM` / JSON coercion (SDK mocked), semantic customer lookup (ragfallback
  mocked), and the version flag.
- Ruff lint + format checks; CI now runs on Python 3.10–3.13.
- SECURITY.md, CODE_OF_CONDUCT.md, issue/PR templates, Dependabot, CITATION.cff.
- README: offline library-usage example and per-extra install commands.

### Changed

- **Python 3.10 is now supported** (`requires-python >= 3.10`; was 3.11+), 3.13 added.
- `mistralai` upper pin removed: `MistralLLM` works with `mistralai` 1.x and 2.x+ (where
  `Mistral` moved to `mistralai.client`).
- `semantic` extra now installs `ragfallback[huggingface,faiss]`, which the vector lookup needs.
- Packaging: `setuptools>=77`, PEP 639 license metadata, author metadata, Changelog URL,
  `ruff` and `langchain-core` (for semantic lookup tests) in the `dev` extra.
- README quick start clarifies that `agentcare up` runs from a repository clone (the services
  and scripts it launches are not part of the wheel). Image links are absolute so they render on PyPI.
- Publish workflow: `skip-existing: true`.

### Fixed

- Semantic customer lookup always fell back to lexical matching on LangChain 1.x because it
  imported `langchain.docstore` (removed); it now uses `langchain_core.documents`.
- `_coerce_json_object` corrupted fenced JSON whose body contained the word "json" (it removed
  the first occurrence anywhere); code fences are now stripped with a proper pattern.
- `MistralLLM.chat` returns text when the SDK returns content chunks instead of a string.

## [0.2.1] - 2026-04-26

### Changed

- Unified README screenshot assets under a single dark/teal visual system.
- Pinned `mistralai` to `<2.0.0` so fresh installs use the SDK API currently
  imported by the Mistral extractor.

## [0.2.0] - 2026-04-25

### Added

- Burnout detection workflow as a first-class AgentCare workflow:
  - `analysis/burnout.py` — MBI-aligned regex taxonomy (EE / DP / rPA dimensions
    plus crisis acuity), saturating sub-score function, and weighted composite
    scoring with risk-band classification.
  - `analysis/trend.py` — Mann–Kendall trend test (with tie correction) plus
    OLS slope and consecutive-deterioration detector for longitudinal triage.
  - `extraction/burnout.py` — Pydantic-validated LLM extractor producing 0–10
    dimension scores, primary stressor, engagement level, sleep/physical-symptom
    flags, crisis flag, and short verbatim quote evidence.
  - `policies/wellness.py` — wellness routing policy mapping (risk_band,
    high_acuity_flag, trend_direction, triage_trigger) to auto-close,
    manager-check-in, or confidential-human-followup decisions.
  - `usecases/wellness.py` — `WellnessDeps` + `process_wellness_execution`
    end-to-end orchestrator mirroring the frontdesk usecase shape.
  - `ports/wellness.py` — `WellnessHistoryStorePort` Protocol.
  - `wellness/store.py` — `JsonWellnessHistoryStore` adapter and
    `get_wellness_history_store()` factory.
  - `usecases/execution_router.py` — `process_agentcare_execution()` and
    `resolve_execution_workflow()` so webhook, sync, and CLI route by
    workflow name (with `wellness`/`burnout` agent-name fallback).
  - `wellness_checkin` registered in `WORKFLOW_REGISTRY`.

- Optional ML and experiments layer (top-level `experiments/`, separate
  install via `pip install -r experiments/requirements.txt`):
  - `experiments/ml/` — feature engineering (27-dim per-employee vector),
    LR / Random Forest / HGBT training pipeline, deterministic synthetic
    corpus generator (3 persona archetypes, 180 employees × 8 sessions).
  - Four reproducible experiments: extraction quality, trend detection,
    predictive modelling with ablation, and adversarial robustness.
  - `scripts/run_all_experiments.sh` — single-command runner.

- Tests: `test_burnout_analysis.py`, `test_trend.py`, `test_wellness_usecase.py`,
  plus existing frontdesk tests confirmed passing without regression.

### Changed

- `services/webhooks/app.py`, `src/agentcare/sync/bolna_sync.py`, and
  `src/agentcare/cli.py` now use `process_agentcare_execution()` so a single
  pipeline serves all four workflows.
- `Settings` gains `wellness_history_store_path` (default
  `artifacts/wellness_history.json`).

## [0.1.0] - 2026-03-07

### Added
- Multi-workflow registry (`frontdesk_booking`, `care_navigation`, `followup_outreach`).
- Cal and FHIR connector paths under unified appointment connector abstraction.
- RAG-backed missing field recovery in frontdesk usecase.
- Doctor routing in core orchestration flow.
- Professionalized confirmation emails and richer calendar booking metadata.
- Dedicated summary columns in `call_executions`:
  - `patient_facing_summary`
  - `internal_ops_summary`
- Analytics endpoint for call detail:
  - `GET /analytics/calls/{execution_id}`

### Changed
- Dashboard UX and call-detail inspection panel.
- Packaging metadata and CLI entrypoint structure.
