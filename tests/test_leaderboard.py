"""Unit tests for keep_or_cut ablation and leaderboard formatting."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keep_or_cut.ablation import analyze_deltas
from keep_or_cut.leaderboard import aggregate, to_markdown
from keep_or_cut.models import AblationDelta, Judgment, Profile


def test_aggregate_ranks_higher_mean_first():
    judgments = [
        Judgment("case1", "profileA", 8, "good", "judge"),
        Judgment("case2", "profileA", 6, "ok", "judge"),
        Judgment("case1", "profileB", 3, "bad", "judge"),
        Judgment("case2", "profileB", 5, "meh", "judge"),
    ]
    rows = aggregate(judgments)
    assert rows[0][0] == "profileA"
    assert rows[0][1] == 7.0
    assert rows[1][0] == "profileB"
    assert rows[1][1] == 4.0


def test_analyze_deltas_recommends_remove_on_hobbling():
    profiles = [
        Profile("claude-opus-5+bare", "anthropic", "claude-opus-5", None),
        Profile("claude-opus-5+example", "anthropic", "claude-opus-5", "examples/context"),
    ]
    judgments = [
        Judgment("case1", "claude-opus-5+bare", 9, "great", "judge"),
        Judgment("case2", "claude-opus-5+bare", 9, "great", "judge"),
        Judgment("case1", "claude-opus-5+example", 6, "hobbled", "judge"),
        Judgment("case2", "claude-opus-5+example", 6, "hobbled", "judge"),
    ]
    deltas = analyze_deltas(judgments, profiles)
    assert len(deltas) == 1
    assert deltas[0].recommendation == "REMOVE"
    assert deltas[0].delta == -3.0


def test_to_markdown_includes_ablation_matrix():
    judgments = [Judgment("case1", "profileA", 7, "fine", "judge")]
    deltas = [
        AblationDelta("claude-opus-5", "example", 9.0, 6.0, -3.0, "REMOVE")
    ]
    md = to_markdown(judgments, deltas)
    assert "profileA" in md
    assert "Skill Ablation & Recommendation Matrix" in md
    assert "REMOVE" in md


if __name__ == "__main__":
    test_aggregate_ranks_higher_mean_first()
    test_analyze_deltas_recommends_remove_on_hobbling()
    test_to_markdown_includes_ablation_matrix()
    print("ok")
