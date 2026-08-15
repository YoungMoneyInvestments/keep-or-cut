"""Unit tests for pairwise Elo ranking and bootstrap CI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keep_or_cut.elo import bootstrap_delta_ci, elo_ratings, pairwise_votes
from keep_or_cut.models import Judgment, Profile


def test_pairwise_votes_tie_and_win():
    judgments = [
        Judgment("case1", "profileA", 8, "a", "judge"),
        Judgment("case1", "profileB", 5, "b", "judge"),
        Judgment("case2", "profileA", 6, "a", "judge"),
        Judgment("case2", "profileB", 6, "b", "judge"),
    ]
    votes = pairwise_votes(judgments)
    assert votes == [
        ("profileA", "profileB", 1.0),
        ("profileA", "profileB", 0.5),
    ]


def test_elo_ratings_orders_by_wins():
    judgments = [
        Judgment("case1", "winner", 10, "x", "judge"),
        Judgment("case1", "loser", 3, "x", "judge"),
        Judgment("case2", "winner", 9, "x", "judge"),
        Judgment("case2", "loser", 4, "x", "judge"),
    ]
    ratings = elo_ratings(judgments, k=32, initial=1000)
    assert ratings["winner"] > ratings["loser"]
    assert set(ratings) == {"winner", "loser"}


def test_bootstrap_delta_ci_shape():
    profiles = [
        Profile("claude-opus-5+bare", "anthropic", "claude-opus-5", None),
        Profile("claude-opus-5+example", "anthropic", "claude-opus-5", "examples/context"),
    ]
    judgments = [
        Judgment("case1", "claude-opus-5+bare", 9, "great", "judge"),
        Judgment("case2", "claude-opus-5+bare", 8, "great", "judge"),
        Judgment("case1", "claude-opus-5+example", 7, "ok", "judge"),
        Judgment("case2", "claude-opus-5+example", 6, "ok", "judge"),
    ]
    ci_rows = bootstrap_delta_ci(judgments, profiles, n_boot=50, seed=0)
    assert len(ci_rows) == 1
    row = ci_rows[0]
    assert row["model"] == "claude-opus-5"
    assert row["skill_name"] == "context"
    assert row["delta"] == -2.0
    assert "ci_low" in row and "ci_high" in row
    assert row["ci_low"] <= row["delta"] <= row["ci_high"]


def test_bootstrap_delta_ci_preserves_repeated_case_draws():
    profiles = [
        Profile("bare", "cli", "m", None),
        Profile("skill", "cli", "m", "/tmp/example"),
    ]
    judgments = [
        Judgment("case1", "bare", 1, "", "judge"),
        Judgment("case1", "skill", 1, "", "judge"),
        Judgment("case2", "bare", 1, "", "judge"),
        Judgment("case2", "skill", 4, "", "judge"),
        Judgment("case3", "bare", 1, "", "judge"),
        Judgment("case3", "skill", 10, "", "judge"),
    ]

    [row] = bootstrap_delta_ci(judgments, profiles, n_boot=1, seed=0)

    # seed=0 draws case2, case2, case1: (3 + 3 + 0) / 3 = 2.
    assert row["ci_low"] == row["ci_high"] == 2.0
