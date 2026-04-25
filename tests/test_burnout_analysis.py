from __future__ import annotations

from agentcare.analysis.burnout import analyze_burnout_context


def test_empty_transcript_returns_low_band() -> None:
    result = analyze_burnout_context(transcript="")
    assert result.risk_band == "low"
    assert result.composite_score == 0.0
    assert result.high_acuity_flag is False


def test_strong_exhaustion_hits_high_band() -> None:
    transcript = (
        "I am completely exhausted, I have no energy left. "
        "I cannot sleep, I keep thinking about work. "
        "I am working every weekend and it never ends. "
        "I feel emotionally drained, like there is nothing left to give."
    )
    result = analyze_burnout_context(transcript=transcript)
    assert result.ee_hits >= 3
    assert result.ee_score >= 6.0
    assert result.risk_band in {"medium", "high"}


def test_crisis_signal_forces_high_acuity() -> None:
    transcript = "Honestly, some days I do not want to wake up. I cannot take it anymore."
    result = analyze_burnout_context(transcript=transcript)
    assert result.high_acuity_flag is True
    assert result.risk_band == "high"
    assert result.recommended_action == "confidential_human_followup_immediate"


def test_llm_score_fusion_overrides_sparse_regex() -> None:
    result = analyze_burnout_context(transcript="Things are okay this week.", llm_ee=8.0, llm_dp=7.0, llm_pa=6.0)
    assert result.ee_score >= 5.0
    assert result.composite_score >= 5.0


def test_low_signal_transcript_stays_low() -> None:
    result = analyze_burnout_context(transcript="Workload is fine. Team is great. Slept well. Shipped two tickets.")
    assert result.risk_band == "low"
    assert result.high_acuity_flag is False


def test_depersonalisation_dimension() -> None:
    transcript = "Honestly I do not care anymore. I am completely checked out, I just show up. I dread Mondays."
    result = analyze_burnout_context(transcript=transcript)
    assert result.dp_hits >= 2
    assert result.dp_score >= 5.0


def test_reduced_accomplishment_dimension() -> None:
    transcript = (
        "I cannot focus, I cannot finish anything. "
        "I feel useless at work. Nothing I do matters. "
        "I am missing deadlines and my work quality has dropped."
    )
    result = analyze_burnout_context(transcript=transcript)
    assert result.pa_hits >= 2
    assert result.pa_score >= 5.0
