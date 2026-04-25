# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and this project follows Semantic Versioning.

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
