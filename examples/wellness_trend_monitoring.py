"""
Weekly burnout check-ins with longitudinal trend detection
=========================================================
Shows    : ``process_wellness_execution`` over six weekly check-in transcripts for
           one employee. Each call is scored on the three Maslach Burnout Inventory
           dimensions (regex signal layer; an LLM score is fused in when Mistral is
           configured), appended to a JSON history, and the Mann-Kendall trend test
           plus a run-length rule decide when to escalate to a human.
           AgentCare produces wellness *signals* for routing; it does not diagnose.
Needs    : ``pip install agentcare``. No API keys, no network.
Run      : python examples/wellness_trend_monitoring.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agentcare.analysis import analyze_burnout_context, detect_trend
from agentcare.extraction import BurnoutExtraction
from agentcare.policies import evaluate_wellness_policy
from agentcare.usecases import WellnessDeps, process_wellness_execution
from agentcare.wellness.store import JsonWellnessHistoryStore

deps = WellnessDeps(
    store=JsonWellnessHistoryStore(Path(tempfile.mkdtemp()) / "wellness_history.json"),
    extract_fields=lambda transcript: BurnoutExtraction(),  # offline: no LLM scores
    analyze_burnout_context=analyze_burnout_context,
    detect_trend=detect_trend,
    evaluate_policy=evaluate_wellness_policy,
)

weeks = [
    "Week was fine, busy but manageable.",
    "A bit overwhelmed with deadlines this week.",
    "Overwhelmed, working late most nights, no time for a break.",
    "Honestly drained. Working weekends and I can't switch off.",
    "Exhausted and drained, I just don't care anymore, it feels pointless.",
    "Burnt out. Exhausted, can't focus, missing deadlines, just going through the motions.",
]

print(f"{'week':<5}{'EE':>6}{'DP':>6}{'PA':>6}{'score':>7}  {'band':<7}{'trend':<14}escalate_to")
for i, transcript in enumerate(weeks, 1):
    res = process_wellness_execution(
        {"id": f"chk-{i}", "employee_id": "emp-042", "transcript": transcript},
        source="example",
        deps=deps,
    )
    a, t, p = res.analysis, res.trend, res.policy
    print(
        f"{i:<5}{a['ee_score']:>6}{a['dp_score']:>6}{a['pa_score']:>6}{a['composite_score']:>7}  "
        f"{a['risk_band']:<7}{t['direction']:<14}{p['escalation_target']}"
    )

print(f"\nMann-Kendall p-value after {t['n']} sessions: {t['mk_p_value']}")
