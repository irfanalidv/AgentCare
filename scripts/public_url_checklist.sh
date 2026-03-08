#!/usr/bin/env bash
set -euo pipefail

cat <<'EOF'
AgentCare Public URL Checklist
==============================

1) Start local services:
   ./scripts/run_llm_gateway.sh
   ./scripts/run_mock_ehr.sh
   ./scripts/run_webhooks.sh

2) Expose services publicly (example with ngrok):
   ngrok http 8020   # mock EHR tools
   ngrok http 8030   # webhook receiver

3) Update .env:
   AGENTCARE_MOCK_EHR_URL=<public-url-for-8020>

4) Generate agent spec with webhook URL:
   python3 -m agentcare templates frontdesk --out frontdesk_agent.json --webhook-url "<public-url-for-8030>/bolna/execution"

5) Create Bolna agent:
   python3 -m agentcare bolna create-agent frontdesk_agent.json

6) (Optional) Register custom model URL in Bolna:
   python3 -m agentcare bolna add-custom-model --url "<public-openai-compatible-llm-gateway-url>/v1"

7) Place call, then inspect:
   python3 -m agentcare bolna call --agent-id "<agent_uuid>" --to "<E.164>"
   python3 -m agentcare bolna execution "<execution_id>"
   python3 -m agentcare eval execution "<execution_id>"

8) Validate memory + email pipeline quickly:
   python3 -m agentcare webhook simulate
EOF

