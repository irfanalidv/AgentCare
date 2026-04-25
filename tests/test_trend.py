from __future__ import annotations

from agentcare.analysis.trend import detect_trend


def test_empty_history() -> None:
    result = detect_trend([])
    assert result.n == 0
    assert result.direction == "stable"
    assert result.triage_trigger is False


def test_clear_deteriorating_trajectory() -> None:
    result = detect_trend([1.0, 2.0, 3.5, 5.0, 6.5, 8.0])
    assert result.direction == "deteriorating"
    assert result.slope_per_session > 0.5
    assert result.triage_trigger is True


def test_clear_improving_trajectory() -> None:
    result = detect_trend([8.0, 7.0, 5.5, 4.0, 2.5, 1.5])
    assert result.direction == "improving"
    assert result.slope_per_session < -0.5


def test_stable_trajectory() -> None:
    result = detect_trend([3.0, 3.2, 2.8, 3.1, 3.0, 2.9])
    assert result.direction == "stable"
    assert result.triage_trigger is False


def test_consecutive_deterioration_triggers_triage() -> None:
    result = detect_trend([2.0, 3.0, 4.0, 5.0, 6.0], deterioration_run_threshold=3)
    assert result.consecutive_deteriorating >= 3
    assert result.triage_trigger is True


def test_high_absolute_score_triggers_triage() -> None:
    result = detect_trend([7.5], score_threshold=7.0)
    assert result.triage_trigger is True


def test_mann_kendall_significance() -> None:
    result = detect_trend([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    assert result.mk_p_value < 0.05
