"""
Synthetic burnout corpus generator.

Generates labelled multi-session check-in transcripts for three persona archetypes:
    1. healthy_stable           — low scores throughout
    2. gradually_deteriorating  — slow rise across sessions, ends moderate-to-high
    3. acute_burnout            — high scores from early sessions

Each persona produces N weekly sessions. Each session is a synthetic transcript
generated from MBI-aligned utterance pools, controlled by latent EE/DP/PA
trajectories. Ground-truth labels are derived from the *latent* trajectory, not
from any extractor — this gives clean supervision for the predictive layer.

Output: JSONL where each line is one session record:
    {employee_id, persona, session_index, week, transcript, latent_ee, latent_dp,
     latent_pa, label_burnout_at_horizon}
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path


# ----- Utterance pools indexed by MBI dimension and severity -----

EE_LOW = [
    "Workload feels manageable this week.",
    "I have been sleeping okay.",
    "I had time for lunch most days.",
    "I logged off by six most evenings.",
    "I took a real weekend.",
]
EE_MED = [
    "I have been pretty tired this week.",
    "I worked late three nights in a row.",
    "I feel a bit drained by Friday.",
    "Sleep has been off lately.",
    "I am running on coffee most days.",
]
EE_HIGH = [
    "I am completely exhausted, I have no energy left.",
    "I cannot sleep, I keep thinking about work.",
    "I am working every weekend and it never ends.",
    "I feel emotionally drained, like there is nothing left to give.",
    "I am running on empty, I cannot keep doing this.",
    "I am too tired to even cook dinner.",
]

DP_LOW = [
    "I am still excited about the project.",
    "The team has been good to work with.",
    "I care about how this lands.",
]
DP_MED = [
    "I am less invested than I used to be.",
    "Some days I am just going through the motions.",
    "I do not feel as connected to the team.",
]
DP_HIGH = [
    "Honestly, I do not care anymore.",
    "I am completely checked out, I just show up.",
    "I dread Mondays. I dread every meeting.",
    "What is even the point of this work.",
    "I feel detached from my colleagues, like a robot.",
]

PA_LOW = [
    "I shipped two things this week and they went well.",
    "I feel I am contributing.",
    "I got good feedback from my lead.",
]
PA_MED = [
    "I missed a couple of small deadlines.",
    "I am not as productive as I used to be.",
    "I am questioning whether I am the right person for this.",
]
PA_HIGH = [
    "I cannot focus, I cannot finish anything.",
    "I feel useless. Nothing I do matters.",
    "I am missing deadlines and the quality has dropped.",
    "I feel like an impostor, I have lost all confidence.",
    "I am failing at my job and I do not know how to fix it.",
]

CRISIS = [
    "Honestly, some days I do not want to wake up.",
    "I have been thinking I cannot take this anymore.",
    "I just want it all to stop.",
]

STRESSORS = {
    "workload": "I have too much on my plate, the volume is unrealistic.",
    "interpersonal": "There is constant friction with my manager.",
    "role_clarity": "I do not even know what I am supposed to be doing.",
    "autonomy": "I cannot make any decisions on my own.",
    "recognition": "I work hard and nobody notices.",
    "values_misalignment": "I do not believe in what we are building.",
    "personal_life": "Things at home are very hard right now.",
}

OPENERS = [
    "Hi, thanks for taking my call.",
    "Hello, glad to chat.",
    "Hey, yeah, I have a few minutes.",
]
CLOSERS = [
    "Thanks for listening.",
    "Yeah, I will think about it.",
    "Okay, talk next week.",
]


def _pick(rng: random.Random, items: list[str], k: int) -> list[str]:
    if not items:
        return []
    k = min(k, len(items))
    return rng.sample(items, k)


def _utterances_for_dim(
    rng: random.Random, score: float, dim: str
) -> list[str]:
    """Score is 0-10 latent. Map to severity tier and sample utterances."""
    pools = {
        "ee": (EE_LOW, EE_MED, EE_HIGH),
        "dp": (DP_LOW, DP_MED, DP_HIGH),
        "pa": (PA_LOW, PA_MED, PA_HIGH),
    }[dim]

    if score < 2.5:
        return _pick(rng, pools[0], 1)
    if score < 5.0:
        # Some low + medium
        return _pick(rng, pools[0], 1) + _pick(rng, pools[1], 1)
    if score < 7.5:
        return _pick(rng, pools[1], 2)
    # High
    n_high = 2 + (1 if score >= 9.0 else 0)
    return _pick(rng, pools[1], 1) + _pick(rng, pools[2], n_high)


def synthesise_transcript(
    rng: random.Random,
    *,
    ee: float,
    dp: float,
    pa: float,
    stressor: str | None = None,
    crisis: bool = False,
    employee_name: str = "Sam",
    role: str = "engineer",
) -> str:
    """Build one session transcript from latent dimension scores."""
    parts: list[str] = []
    parts.append(f"Agent: Hi {employee_name}, this is your weekly wellness check-in. How has the week been?")
    parts.append(f"{employee_name}: " + rng.choice(OPENERS))

    user_lines = (
        _utterances_for_dim(rng, ee, "ee")
        + _utterances_for_dim(rng, dp, "dp")
        + _utterances_for_dim(rng, pa, "pa")
    )
    rng.shuffle(user_lines)

    if stressor and stressor in STRESSORS:
        user_lines.insert(rng.randint(0, len(user_lines)), STRESSORS[stressor])

    if crisis:
        user_lines.append(rng.choice(CRISIS))

    # Interleave with brief agent prompts
    agent_prompts = [
        "Agent: That sounds heavy. Can you tell me more?",
        "Agent: How have you been sleeping?",
        "Agent: How is the team feeling to you right now?",
        "Agent: Are you finding time to recover?",
        "Agent: What is taking up most of your energy?",
    ]
    rng.shuffle(agent_prompts)

    for i, line in enumerate(user_lines):
        if i > 0 and i % 2 == 0 and agent_prompts:
            parts.append(agent_prompts.pop())
        parts.append(f"{employee_name}: {line}")

    parts.append(f"{employee_name}: " + rng.choice(CLOSERS))
    parts.append("Agent: Thank you for sharing. Take care, talk next week.")
    return "\n".join(parts)


# ----- Persona trajectories -----

@dataclass
class Persona:
    employee_id: str
    archetype: str
    name: str
    role: str
    n_sessions: int
    seed: int
    primary_stressor: str | None


def _trajectory(archetype: str, n: int, rng: random.Random) -> tuple[list[float], list[float], list[float], list[bool]]:
    """Return latent (ee, dp, pa, crisis_flag) trajectories of length n."""
    ee = []
    dp = []
    pa = []
    crisis_flags = [False] * n

    if archetype == "healthy_stable":
        for _ in range(n):
            ee.append(max(0.0, rng.gauss(1.5, 0.8)))
            dp.append(max(0.0, rng.gauss(1.2, 0.7)))
            pa.append(max(0.0, rng.gauss(1.5, 0.8)))

    elif archetype == "gradually_deteriorating":
        ee_start = rng.uniform(1.5, 3.0)
        ee_end = rng.uniform(6.5, 8.5)
        dp_start = rng.uniform(1.0, 2.5)
        dp_end = rng.uniform(5.5, 7.5)
        pa_start = rng.uniform(1.5, 3.0)
        pa_end = rng.uniform(5.0, 7.0)
        for i in range(n):
            t = i / max(1, n - 1)
            ee.append(max(0.0, min(10.0, ee_start + (ee_end - ee_start) * t + rng.gauss(0, 0.5))))
            dp.append(max(0.0, min(10.0, dp_start + (dp_end - dp_start) * t + rng.gauss(0, 0.5))))
            pa.append(max(0.0, min(10.0, pa_start + (pa_end - pa_start) * t + rng.gauss(0, 0.5))))

    elif archetype == "acute_burnout":
        for i in range(n):
            ee.append(max(0.0, min(10.0, rng.gauss(8.0, 0.8))))
            dp.append(max(0.0, min(10.0, rng.gauss(7.0, 0.9))))
            pa.append(max(0.0, min(10.0, rng.gauss(6.5, 0.9))))
        # Small chance of crisis signal in the last 2 sessions
        if rng.random() < 0.20:
            crisis_flags[-1] = True
        if rng.random() < 0.10 and n >= 2:
            crisis_flags[-2] = True

    else:
        raise ValueError(f"Unknown archetype: {archetype}")

    return (
        [round(v, 2) for v in ee],
        [round(v, 2) for v in dp],
        [round(v, 2) for v in pa],
        crisis_flags,
    )


def _label_for_persona(ee: list[float], dp: list[float], horizon_start: int) -> int:
    """1 if any session at or after horizon_start has ee>=7 and dp>=6."""
    for i in range(horizon_start, len(ee)):
        if ee[i] >= 7.0 and dp[i] >= 6.0:
            return 1
    return 0


# ----- Public corpus generation -----

NAMES = [
    "Sam", "Priya", "Alex", "Maya", "Jordan", "Riya", "Chris", "Aisha",
    "Devon", "Tara", "Noor", "Kiran", "Leo", "Zara", "Arjun", "Mira",
]
ROLES = ["engineer", "designer", "analyst", "manager", "researcher", "PM"]


def generate_corpus(
    *,
    n_per_archetype: int = 60,
    n_sessions: int = 8,
    horizon_start: int = 4,
    seed: int = 42,
    output_path: str = "experiments/data/synthetic_corpus.jsonl",
) -> dict:
    """
    Generate a labelled synthetic corpus.

    Total employees: 3 * n_per_archetype.
    Total sessions: 3 * n_per_archetype * n_sessions.

    Label horizon: label is positive if burnout criterion is met in any session
    at index >= horizon_start (i.e. predicting from the first horizon_start
    sessions whether it shows up later).
    """
    master_rng = random.Random(seed)
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    archetypes = ["healthy_stable", "gradually_deteriorating", "acute_burnout"]
    personas: list[Persona] = []
    eid = 0
    for arch in archetypes:
        for _ in range(n_per_archetype):
            personas.append(Persona(
                employee_id=f"emp_{eid:04d}",
                archetype=arch,
                name=master_rng.choice(NAMES),
                role=master_rng.choice(ROLES),
                n_sessions=n_sessions,
                seed=master_rng.randint(1, 10**9),
                primary_stressor=(
                    master_rng.choice(list(STRESSORS.keys()))
                    if arch != "healthy_stable" or master_rng.random() < 0.2
                    else None
                ),
            ))
            eid += 1

    counts = {"healthy_stable": 0, "gradually_deteriorating": 0, "acute_burnout": 0, "positive_labels": 0}

    with out_path.open("w", encoding="utf-8") as fh:
        for p in personas:
            rng = random.Random(p.seed)
            ee_traj, dp_traj, pa_traj, crisis_flags = _trajectory(p.archetype, p.n_sessions, rng)
            label = _label_for_persona(ee_traj, dp_traj, horizon_start=horizon_start)
            counts[p.archetype] += 1
            counts["positive_labels"] += label

            for s in range(p.n_sessions):
                transcript = synthesise_transcript(
                    rng,
                    ee=ee_traj[s], dp=dp_traj[s], pa=pa_traj[s],
                    stressor=p.primary_stressor if s % 3 == 0 else None,
                    crisis=crisis_flags[s],
                    employee_name=p.name,
                    role=p.role,
                )
                rec = {
                    "employee_id": p.employee_id,
                    "archetype": p.archetype,
                    "name": p.name,
                    "role": p.role,
                    "session_index": s,
                    "week": s,
                    "latent_ee": ee_traj[s],
                    "latent_dp": dp_traj[s],
                    "latent_pa": pa_traj[s],
                    "latent_crisis": bool(crisis_flags[s]),
                    "primary_stressor": p.primary_stressor,
                    "transcript": transcript,
                    "label_burnout_at_horizon": label,
                    "horizon_start": horizon_start,
                }
                fh.write(json.dumps(rec) + "\n")

    summary = {
        "n_employees": len(personas),
        "n_sessions_total": len(personas) * n_sessions,
        "by_archetype": {k: counts[k] for k in archetypes},
        "n_positive_labels": counts["positive_labels"],
        "positive_rate": round(counts["positive_labels"] / len(personas), 3),
        "output_path": str(out_path),
    }
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    generate_corpus()
