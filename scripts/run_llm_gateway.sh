#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="$(pwd)/src:$(pwd):${PYTHONPATH:-}"
exec python3 -m uvicorn services.llm_gateway.app:app --host 0.0.0.0 --port 8010

