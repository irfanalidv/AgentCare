from __future__ import annotations

import json
import time
from pathlib import Path

from agentcare.bolna import BolnaClient
from agentcare.eval import evaluate_transcript
from agentcare.llm import MistralLLM
from agentcare.settings import settings
from agentcare.templates import build_frontdesk_agent_spec


TERMINAL_STATUSES = {
    "completed",
    "call-disconnected",
    "no-answer",
    "busy",
    "failed",
    "canceled",
    "balance-low",
}


def main() -> None:
    if not settings.bolna_api_key:
        raise SystemExit("Missing BOLNA_API_KEY")
    if not settings.mistral_api_key:
        raise SystemExit("Missing MISTRAL_API_KEY (required for evaluation)")

    artifacts_dir = Path("artifacts")
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    spec = build_frontdesk_agent_spec(
        llm_base_url=settings.agentcare_llm_gateway_url,
        llm_model=settings.mistral_model,
        mock_ehr_base_url=settings.agentcare_mock_ehr_url,
    )

    with BolnaClient(api_key=settings.bolna_api_key, base_url=settings.bolna_base_url) as bolna:
        agent = bolna.create_agent_v2(agent_config=spec["agent_config"], agent_prompts=spec["agent_prompts"])
        print(f"created agent_id={agent.agent_id}")

        # NOTE: Replace with a real E.164 number you can legally call.
        to_number = "+15550000001"
        call = bolna.make_call(agent_id=agent.agent_id, recipient_phone_number=to_number)
        print(f"queued execution_id={call.execution_id}")

        # Poll execution until terminal status.
        delay_s = 2.0
        while True:
            ex = bolna.get_execution(execution_id=call.execution_id)
            status = ex.status or "unknown"
            print(f"status={status}")
            if status in TERMINAL_STATUSES:
                break
            time.sleep(delay_s)
            delay_s = min(delay_s * 1.5, 15.0)

    # Evaluate transcript (if present).
    llm = MistralLLM(api_key=settings.mistral_api_key, model=settings.mistral_model)
    eval_result = None
    if ex.transcript:
        eval_result = evaluate_transcript(
            llm=llm,
            transcript=ex.transcript,
            context={"execution_id": call.execution_id, "agent_id": agent.agent_id},
        )

    out = {
        "agent": agent.model_dump(),
        "call": call.model_dump(),
        "execution": ex.model_dump(),
        "eval": eval_result.model_dump() if eval_result else None,
    }
    out_path = artifacts_dir / f"run_{call.execution_id}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str), "utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

