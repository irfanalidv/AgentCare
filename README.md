# AgentCare

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/pypi/v/agentcare.svg)](https://pypi.org/project/agentcare/)
[![PyPI downloads](https://img.shields.io/pypi/dm/agentcare.svg)](https://pypi.org/project/agentcare/)
[![Pepy total downloads](https://static.pepy.tech/badge/agentcare)](https://pepy.tech/project/agentcare)

![AgentCare Framework](docs/assets/screenshots/agentcare-framework-overview.png)

AgentCare is a Python framework for voice-AI workflows. It takes phone-call lifecycle events from a telephony provider, runs the transcript through a regex+LLM extractor, applies a domain-specific analysis and policy layer, and dispatches the resulting action through provider-agnostic adapters (Cal for booking, Resend for email, JSON or Postgres for memory).

Four workflows ship registered: three healthcare front-desk workflows and one workplace burnout check-in. The `wellness_checkin` workflow and the `experiments/` benchmark layer were built as the M.Sc. Data Science & AI individual project at IISER Tirupati, prepared for May 2026 submission; the rest of the framework predates that work and continues as an open-source library.

```
pip install agentcare
```

## Contents

- [Quick start](#quick-start)
- [Workflows](#workflows)
- [The wellness workflow](#the-wellness-workflow)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Reproducible experiments](#reproducible-experiments)
- [CLI reference](#cli-reference)
- [Tests and contribution](#tests-and-contribution)
- [Project context](#project-context)

## Quick start

```bash
pip install agentcare
cp .env.example .env       # add BOLNA_API_KEY and MISTRAL_API_KEY
python -m agentcare up
```

`up` starts the local stack (webhook adapter, analytics API, dashboard, mock EHR, local OpenAI-compatible LLM gateway) on five ports. `python -m agentcare up --dry-run` validates configuration without starting anything.

For local development:

```bash
git clone https://github.com/irfanalidv/AgentCare
cd AgentCare
pip install -e ".[web,postgres,email,semantic,dev]"
pytest -q
```

After `up` completes, the running services are:

| Service          | URL                              |
| ---------------- | -------------------------------- |
| Dashboard        | http://127.0.0.1:8050            |
| Analytics API    | http://127.0.0.1:8040/healthz    |
| Webhooks         | http://127.0.0.1:8030/healthz    |
| Mock EHR         | http://127.0.0.1:8020/healthz    |
| LLM gateway      | http://127.0.0.1:8010/healthz    |

![Dashboard overview](docs/assets/screenshots/dashboard-overview.svg)

## Workflows

![Workflows overview](docs/assets/screenshots/agentcare-workflows-overview.svg)

```bash
$ python -m agentcare framework list-workflows
{
  "workflows": [
    {
      "name": "frontdesk_booking",
      "description": "Schedule/reschedule appointments with optional calendar automation.",
      "category": "scheduling",
      "required_integrations": ["bolna", "llm_gateway", "appointment_connector", "email_optional"]
    },
    {
      "name": "care_navigation",
      "description": "General care coordination and intake routing, tool-friendly but booking-light.",
      "category": "care_coordination",
      "required_integrations": ["bolna", "llm_gateway", "customer_memory"]
    },
    {
      "name": "followup_outreach",
      "description": "Proactive follow-up calls for reminders and unresolved case closure.",
      "category": "outreach",
      "required_integrations": ["bolna", "llm_gateway", "analytics", "customer_memory"]
    },
    {
      "name": "wellness_checkin",
      "description": "Weekly burnout check-in with MBI-aligned signals and longitudinal trend tracking.",
      "category": "wellness",
      "required_integrations": ["bolna", "llm_gateway", "wellness_history"]
    }
  ]
}
```

All four workflows share the same call-ingestion, extraction, and persistence machinery. What differs is the analysis module (`src/agentcare/analysis/`), the policy module (`src/agentcare/policies/`), and the use-case orchestrator (`src/agentcare/usecases/`). To add a workflow, register a `WorkflowDefinition` in `workflows/registry.py` and write a use-case module wired through the existing ports.

To create a Bolna agent for one of the registered workflows:

```bash
python -m agentcare framework create-agent --workflow frontdesk_booking
```

## The wellness workflow

`wellness_checkin` runs a short weekly conversational check-in with an employee, scores the transcript on the three Maslach Burnout Inventory (MBI) dimensions, tracks the score history per employee, and routes to one of three actions: auto-close, manager check-in, or confidential human follow-up.

The analysis layer (`analysis/burnout.py`) scores emotional exhaustion, depersonalisation, and reduced personal accomplishment using a regex taxonomy. The LLM extractor (`extraction/burnout.py`) returns 0–10 scores for each dimension under a Pydantic-validated JSON schema with verbatim quote evidence. The two are fused with a 0.75/0.25 LLM/regex weighting.

The trend layer (`analysis/trend.py`) applies the Mann–Kendall test (with tie correction) and an OLS slope to the per-employee composite score series. A triage trigger fires when any of three conditions hold: three consecutive worsening sessions, a composite crossing 7.0, or a deteriorating trend with the latest composite at or above 5.0. Crisis cues (explicit hopelessness, self-harm references, breakdown language) are scored on a separate acuity flag that overrides the policy unconditionally.

The history store has a `WellnessHistoryStorePort` interface and a JSON adapter by default (`artifacts/wellness_history.json`). A Postgres adapter can be added without changing use-case code.

Operations data is exposed through the dashboard API:

```
GET /api/wellness/cohort                  cohort summary by latest band
GET /api/wellness/flagged                 employees flagged for follow-up
GET /api/wellness/employee/{employee_id}  full session history + recomputed trend
GET /api/wellness/series?limit=50         per-employee composite trajectories
```

## Configuration

The runtime reads from environment variables, conventionally loaded from `.env`. Two keys are mandatory: `BOLNA_API_KEY` for call orchestration and `MISTRAL_API_KEY` for extraction. Everything else has a default.

For the full feature surface (booking through Cal, confirmation email through Resend, Postgres-backed memory) set the variables below.

| Variable | Purpose |
|---|---|
| `BOLNA_BASE_URL`, `BOLNA_AGENT_ID`, `BOLNA_FROM_NUMBER` | Provider endpoint, default agent, outbound caller identity |
| `MISTRAL_MODEL` | Extraction and evaluation model |
| `AGENTCARE_LLM_GATEWAY_URL`, `AGENTCARE_MOCK_EHR_URL` | Local service endpoints |
| `CAL_API_KEY`, `CAL_EVENT_TYPE_ID`, `CAL_TIMEZONE` | Booking integration |
| `RESEND_API_KEY`, `AGENTCARE_EMAIL_FROM` | Email delivery |
| `CUSTOMER_STORE_BACKEND`, `CUSTOMER_STORE_PATH` | Memory backend (`auto` / `json` / `postgres`) and JSON path |
| `WELLNESS_HISTORY_STORE_PATH` | Default `artifacts/wellness_history.json` |
| `PROCESSED_EXECUTIONS_PATH` | Idempotency tracking |
| `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_DB_URL` | Postgres-backed persistence |
| `APPOINTMENT_CONNECTOR_BACKEND` | `cal` or `mock` |
| `FRONTDESK_POLICY_PATH` | Load policy rules from JSON |

`artifacts/` is git-ignored; do not commit raw call data, and do not commit `.env`.

## Architecture

The codebase is laid out as ports + adapters with use-cases in the middle:

```
src/agentcare/
  usecases/         workflow orchestration (one module per workflow)
  ports/            interface contracts
  connectors/       appointment connectors (cal, mock)
  customer/         memory store implementations (json, postgres)
  email/            resend notifier
  analysis/         risk and signal analysis (healthcare, burnout, trend)
  extraction/       transcript to structured data (LLM + regex)
  policies/         policy decision logic (frontdesk, wellness)
  workflows/        registry and metadata
  wellness/         wellness history store
  cli.py            Typer command entry points

services/
  webhooks/         call lifecycle ingestion (FastAPI)
  analytics/        operations metrics API
  dashboard/        dashboard API + static UI
  llm_gateway/      local OpenAI-compatible endpoint
  mock_ehr/         local mock scheduling

experiments/        reproducible benchmark layer (separate install)
scripts/            development and operational helpers
```

A single execution router (`usecases/execution_router.py`) selects the workflow at runtime by explicit `workflow` argument, by Bolna agent name fallback, or by registry default. The same router is used by webhook ingestion, the Bolna sync command, the dashboard, and the CLI.

![Architecture](docs/assets/screenshots/agentcare-architecture-visual.svg)
![Data model](docs/assets/screenshots/agentcare-data-model.svg)

The four operational entities are `customer_profiles`, `call_executions`, `appointments`, and `call_lifecycle_events`. The wellness workflow adds a per-employee score history alongside these.

## Reproducible experiments

`experiments/` is a separate benchmark layer that pulls in scikit-learn, numpy, and matplotlib. The runtime does not need them.

```bash
pip install -r experiments/requirements.txt
bash scripts/run_all_experiments.sh
```

The script generates a deterministic synthetic corpus (180 employees, 8 sessions each, seed 42) and runs four experiments in sequence: extraction quality, trend detection across window sizes, predictive modelling at a four-session horizon with a feature ablation, and adversarial robustness on edge-case transcripts. Total runtime is roughly 30 seconds. Outputs (JSON metrics, CSV predictions, PNG figures, pickled models) land in `experiments/output/`.

Reference numbers from the regex-only run on the default seed:

| Experiment | Metric | Value |
|---|---|---|
| Trend detection, window=8 | Accuracy | 0.972 |
| Predictive (LogReg) | Test F1 | 0.952 |
| Predictive (LogReg) | Test ROC-AUC | 0.997 |
| Adversarial | Band accuracy | 0.833 |
| Adversarial | False positives | 0 |

These validate the pipeline mechanics on synthetic data and are not external claims about real-world burnout detection. See `experiments/README.md` for interpretation and the limitations discussion.

## CLI reference

```bash
python -m agentcare doctor                      # diagnose configuration
python -m agentcare init-artifacts              # create artifacts/ directory
python -m agentcare framework provider-test     # check provider connectivity
python -m agentcare framework list-workflows    # registered workflows (JSON)
python -m agentcare framework create-agent --workflow wellness_checkin
python -m agentcare framework process-execution --execution-json artifacts/sample_execution.json
python -m agentcare bolna voices                # list available voices
python -m agentcare bolna call --phone-number ...
python -m agentcare bolna sync-executions
python -m agentcare up --dry-run                # validate without starting
./scripts/check_no_secrets.sh                   # pre-commit safety check
```

## Tests and contribution

```bash
pytest -q
python -m build && twine check dist/*
```

The suite covers burnout analysis, trend detection, the wellness use-case, the execution router, the analytics endpoints, and the existing frontdesk regression tests. See `CONTRIBUTING.md` for the development workflow and `CHANGELOG.md` for the version history.

## Project context

The healthcare workflows (`frontdesk_booking`, `care_navigation`, `followup_outreach`) and the framework itself are an independent open-source project published on PyPI under the MIT license. The `wellness_checkin` workflow and the `experiments/` benchmark layer were added in v0.2.0 (April–May 2026) as the deliverable for the M.Sc. Data Science & AI individual project at the Indian Institute of Science Education and Research (IISER) Tirupati. The methodology (MBI dimension mapping, Mann–Kendall trend detection, predictive modelling at a multi-session horizon) and the experimental results are documented in the project's end-semester report. The burnout layer is the academic contribution; the rest is the surrounding library.
