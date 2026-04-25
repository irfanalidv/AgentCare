"""
Burnout signal analysis aligned to Maslach Burnout Inventory dimensions.

This is a signal layer over conversational text. It does not diagnose burnout;
it produces conservative, evidence-anchored features for wellness routing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class BurnoutAnalysis:
    ee_hits: int = 0
    dp_hits: int = 0
    pa_hits: int = 0
    ee_tags: list[str] = field(default_factory=list)
    dp_tags: list[str] = field(default_factory=list)
    pa_tags: list[str] = field(default_factory=list)
    ee_score: float = 0.0
    dp_score: float = 0.0
    pa_score: float = 0.0
    composite_score: float = 0.0
    risk_band: str = "low"
    recommended_action: str = "continue_monitoring"
    high_acuity_flag: bool = False


_EE_PATTERNS: list[tuple[str, str]] = [
    (r"\bexhaust(ed|ing|ion)\b", "exhaustion_explicit"),
    (r"\bdrained\b", "drained"),
    (r"\bburn(ed|t)?[\s-]?out\b", "burnt_out_explicit"),
    (r"\b(can'?t|cannot) (cope|keep up|do this anymore)\b", "cant_cope"),
    (r"\boverwhelm(ed|ing)\b", "overwhelmed"),
    (r"\b(too much|too many) (work|things|deadlines|meetings)\b", "workload_excess"),
    (r"\bworking (late|weekends|all the time|nights)\b", "extended_hours"),
    (r"\bno (time|energy|break)\b", "no_recovery"),
    (r"\bnot sleeping\b", "sleep_disruption"),
    (r"\b(can'?t|cannot) (sleep|relax|switch off|disconnect)\b", "cant_disconnect"),
    (r"\b(constantly|always) (tired|fatigue)\b", "chronic_fatigue"),
    (r"\bno energy\b", "low_energy"),
    (r"\bemotionally (drained|spent|empty)\b", "emotional_depletion"),
]

_DP_PATTERNS: list[tuple[str, str]] = [
    (r"\b(don'?t|do not) care anymore\b", "apathy_explicit"),
    (r"\bjust going through the motions\b", "going_through_motions"),
    (r"\bcheck(ing|ed) out\b", "checked_out"),
    (r"\bdisengag(ed|ing)\b", "disengaged"),
    (r"\bcynical\b", "cynicism_explicit"),
    (r"\bpointless\b", "pointless"),
    (r"\b(hate|dread) (work|my job|going in|mondays)\b", "work_aversion"),
    (r"\bwhat'?s the point\b", "questioning_purpose"),
    (r"\b(not|no longer) (engaged|invested|excited)\b", "loss_of_engagement"),
    (r"\b(distant|detached) from (team|colleagues|clients|patients)\b", "interpersonal_detachment"),
    (r"\b(robotic|mechanical|automatic) at work\b", "mechanical_work"),
]

_PA_PATTERNS: list[tuple[str, str]] = [
    (r"\b(not|no longer) (effective|making (a )?difference|productive)\b", "ineffective"),
    (r"\bnothing (i do )?matters\b", "futility"),
    (r"\b(failing|failure) at (work|my job)\b", "perceived_failure"),
    (r"\b(can'?t|cannot) (focus|concentrate|finish|get anything done)\b", "performance_decline"),
    (r"\b(useless|worthless) at work\b", "self_devaluation"),
    (r"\bnot good enough\b", "self_doubt"),
    (r"\b(impostor|imposter)\b", "impostor"),
    (r"\bmissing deadlines\b", "missed_deadlines"),
    (r"\b(my )?work quality (has )?(dropped|slipped|declined)\b", "quality_decline"),
    (r"\b(losing|lost) (confidence|motivation)\b", "motivation_loss"),
]

_HIGH_ACUITY_PATTERNS: list[tuple[str, str]] = [
    (r"\bsuicid(al|e)\b", "suicidal_ideation"),
    (r"\bself[- ]harm\b", "self_harm"),
    (r"\b(want|wish) to (die|disappear|not (exist|wake up))\b", "wish_to_die"),
    (r"\bend(ing)? it all\b", "end_it_all"),
    (r"\bno (way|reason) to (live|go on)\b", "hopelessness_acute"),
    (r"\b(can'?t|cannot) take (it|this) anymore\b", "breaking_point"),
    (r"\bhaving a breakdown\b", "breakdown"),
]


def _scan(text: str, patterns: list[tuple[str, str]]) -> tuple[int, list[str]]:
    hits = 0
    tags: list[str] = []
    seen: set[str] = set()
    for pattern, tag in patterns:
        if re.search(pattern, text, flags=re.I):
            hits += 1
            if tag not in seen:
                tags.append(tag)
                seen.add(tag)
    return hits, tags


def _hits_to_score(hits: int) -> float:
    if hits <= 0:
        return 0.0
    return round(min(10.0, 10.0 * (1 - 0.55**hits)), 2)


def _fuse(regex_score: float, llm_score: float | None) -> float:
    if llm_score is None:
        return regex_score
    return round(min(10.0, max(0.0, 0.75 * float(llm_score) + 0.25 * regex_score)), 2)


def _band(score: float, high_acuity: bool) -> tuple[str, str]:
    if high_acuity:
        return "high", "confidential_human_followup_immediate"
    if score >= 7.0:
        return "high", "confidential_human_followup"
    if score >= 4.0:
        return "medium", "manager_check_in_suggested"
    return "low", "continue_monitoring"


def analyze_burnout_context(
    *,
    transcript: str | None,
    reason: str | None = None,
    llm_ee: float | None = None,
    llm_dp: float | None = None,
    llm_pa: float | None = None,
) -> BurnoutAnalysis:
    text = " ".join([reason or "", transcript or ""]).strip().lower()
    if not text:
        return BurnoutAnalysis()

    ee_hits, ee_tags = _scan(text, _EE_PATTERNS)
    dp_hits, dp_tags = _scan(text, _DP_PATTERNS)
    pa_hits, pa_tags = _scan(text, _PA_PATTERNS)
    acuity_hits, acuity_tags = _scan(text, _HIGH_ACUITY_PATTERNS)

    ee_score = _fuse(_hits_to_score(ee_hits), llm_ee)
    dp_score = _fuse(_hits_to_score(dp_hits), llm_dp)
    pa_score = _fuse(_hits_to_score(pa_hits), llm_pa)
    composite = round(0.45 * ee_score + 0.35 * dp_score + 0.20 * pa_score, 2)

    high_acuity = acuity_hits > 0
    band, action = _band(composite, high_acuity)
    if high_acuity:
        ee_tags = list(dict.fromkeys(ee_tags + acuity_tags))

    return BurnoutAnalysis(
        ee_hits=ee_hits,
        dp_hits=dp_hits,
        pa_hits=pa_hits,
        ee_tags=ee_tags[:6],
        dp_tags=dp_tags[:6],
        pa_tags=pa_tags[:6],
        ee_score=ee_score,
        dp_score=dp_score,
        pa_score=pa_score,
        composite_score=composite,
        risk_band=band,
        recommended_action=action,
        high_acuity_flag=high_acuity,
    )
