"""Pairwise Elo / Bradley-Terry ranking from judged scores."""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import replace

from keep_or_cut.ablation import analyze_deltas
from keep_or_cut.models import Judgment, Profile


def pairwise_votes(judgments: list[Judgment]) -> list[tuple[str, str, float]]:
    """Per-case pairwise outcomes: (profile_a, profile_b, outcome).

    outcome is 1.0 if profile_a scored higher, 0.0 if lower, 0.5 on ties.
    Profiles are compared in stable sorted order within each case_id.
    """
    by_case: dict[str, dict[str, int]] = defaultdict(dict)
    for j in judgments:
        if j.score <= 0:
            continue
        by_case[j.case_id][j.profile_id] = j.score

    votes: list[tuple[str, str, float]] = []
    for case_id in sorted(by_case):
        profile_ids = sorted(by_case[case_id])
        scores = by_case[case_id]
        for i, profile_a in enumerate(profile_ids):
            for profile_b in profile_ids[i + 1 :]:
                score_a = scores[profile_a]
                score_b = scores[profile_b]
                if score_a > score_b:
                    outcome = 1.0
                elif score_a < score_b:
                    outcome = 0.0
                else:
                    outcome = 0.5
                votes.append((profile_a, profile_b, outcome))
    return votes


def elo_ratings(
    judgments: list[Judgment],
    k: float = 32,
    initial: float = 1000,
) -> dict[str, float]:
    """Iterate pairwise votes in stable order and return final Elo per profile."""
    ratings: dict[str, float] = {}

    def rating(profile_id: str) -> float:
        if profile_id not in ratings:
            ratings[profile_id] = initial
        return ratings[profile_id]

    for profile_a, profile_b, outcome in pairwise_votes(judgments):
        ra = rating(profile_a)
        rb = rating(profile_b)
        expected_a = 1.0 / (1.0 + 10 ** ((rb - ra) / 400))
        expected_b = 1.0 - expected_a
        ratings[profile_a] = ra + k * (outcome - expected_a)
        ratings[profile_b] = rb + k * ((1.0 - outcome) - expected_b)

    return ratings


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p / 100.0
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] + weight * (ordered[high] - ordered[low])


def bootstrap_delta_ci(
    judgments: list[Judgment],
    profiles: list[Profile],
    n_boot: int = 500,
    seed: int = 0,
) -> list[dict]:
    """Bootstrap confidence intervals for ablation deltas by resampling cases."""
    case_ids = sorted({j.case_id for j in judgments if j.score > 0})
    if not case_ids:
        return []

    point_deltas = analyze_deltas(judgments, profiles)
    if not point_deltas:
        return []

    valid_judgments = [j for j in judgments if j.score > 0]
    samples_by_key: dict[tuple[str, str], list[float]] = defaultdict(list)
    rng = random.Random(seed)

    for _ in range(n_boot):
        sampled_cases = [rng.choice(case_ids) for _ in case_ids]
        boot_judgments: list[Judgment] = []
        for draw, case_id in enumerate(sampled_cases):
            boot_judgments.extend(
                replace(j, case_id=f"{draw}:{case_id}")
                for j in valid_judgments
                if j.case_id == case_id
            )

        for delta in analyze_deltas(boot_judgments, profiles):
            samples_by_key[(delta.model, delta.skill_name)].append(delta.delta)

    results: list[dict] = []
    for point in point_deltas:
        key = (point.model, point.skill_name)
        samples = samples_by_key.get(key, [])
        if not samples:
            continue
        results.append(
            {
                "model": point.model,
                "skill_name": point.skill_name,
                "delta": point.delta,
                "ci_low": round(_percentile(samples, 2.5), 2),
                "ci_high": round(_percentile(samples, 97.5), 2),
            }
        )
    return results
