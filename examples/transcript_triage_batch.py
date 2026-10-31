"""
Triage a batch of call transcripts (no LLM required)
===================================================
Shows    : the deterministic layers you can use on their own: healthcare risk and
           category analysis, specialty routing to a doctor directory, the booking
           policy (auto-book / escalate / SLA), and MBI-aligned burnout signals for
           wellness lines. Useful for back-filling analytics over historical calls.
           If MISTRAL_API_KEY is set, structured fields are also extracted with
           ``extract_conversation_fields`` (this part calls the Mistral API).
Needs    : ``pip install agentcare``. Offline by default.
Run      : python examples/transcript_triage_batch.py
"""

from __future__ import annotations

from agentcare.analysis import analyze_burnout_context, analyze_healthcare_context
from agentcare.doctor import assign_doctor
from agentcare.extraction import extract_conversation_fields
from agentcare.policies import evaluate_frontdesk_policy
from agentcare.settings import settings

transcripts = {
    "c1": (
        "new_appointment",
        "I'd like to book a dermatology visit, this skin rash keeps coming back.",
    ),
    "c2": ("reschedule", "Can I move my appointment to Friday? Nothing has changed with my back."),
    "c3": ("new_appointment", "I fainted at work today and my chest feels tight."),
    "c4": (
        "care_coordination",
        "Since the panic attacks started I can't sleep, I need someone to talk to.",
    ),
}

print(f"{'id':<4}{'category':<18}{'risk':<8}{'doctor':<22}{'auto-book':<11}{'queue':<17}sla_h")
for cid, (intent, text) in transcripts.items():
    health = analyze_healthcare_context(transcript=text, reason=None, intent=intent)
    doctor = assign_doctor(reason=text, intent=intent)
    policy = evaluate_frontdesk_policy(intent=intent, risk_level=health.risk_level)
    print(
        f"{cid:<4}{health.care_category:<18}{health.risk_level:<8}{doctor.doctor_specialty:<22}"
        f"{policy.allow_auto_booking!s:<11}{policy.triage_queue:<17}{policy.follow_up_sla_hours}"
    )

burnout = analyze_burnout_context(
    transcript="I'm exhausted, working weekends, and honestly I don't care anymore."
)
print(
    f"\nwellness line: composite={burnout.composite_score} band={burnout.risk_band} "
    f"tags={burnout.ee_tags + burnout.dp_tags} -> {burnout.recommended_action}"
)

if settings.mistral_api_key:  # optional: needs network + key
    fields = extract_conversation_fields(transcripts["c1"][1])
    print("\nMistral extraction for c1:", fields.model_dump(exclude_none=True))
else:
    print("\n(set MISTRAL_API_KEY to also run LLM field extraction)")
