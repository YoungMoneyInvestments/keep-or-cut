"""Fail-closed matrix: paired deltas only, no KEEP from disjoint cases."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keep_or_cut.ablation import analyze_deltas
from keep_or_cut.cli import _expand_dirs
from keep_or_cut.models import AblationDelta, Judgment, Profile


def test_unpaired_cases_do_not_emit_keep():
    profiles = [
        Profile("m+bare", "cli", "m", None),
        Profile("m+skill", "cli", "m", "/tmp/example-skill", class_id="skills/example", kind="skills"),
    ]
    judgments = [
        Judgment("case-a", "m+bare", 1, "bare only", "j"),
        Judgment("case-b", "m+skill", 10, "other case", "j"),
    ]
    assert analyze_deltas(judgments, profiles) == []


def test_paired_delta_uses_shared_cases_only():
    profiles = [
        Profile("m+bare", "cli", "m", None),
        Profile("m+skill", "cli", "m", "/tmp/example-skill", class_id="skills/example", kind="skills"),
    ]
    judgments = [
        Judgment("case-a", "m+bare", 6, "", "j"),
        Judgment("case-a", "m+skill", 8, "", "j"),
        Judgment("case-b", "m+skill", 10, "", "j"),
    ]
    deltas = analyze_deltas(judgments, profiles)
    assert len(deltas) == 1
    assert deltas[0].delta == 2.0
    assert deltas[0].n_paired == 1
    assert deltas[0].recommendation == "KEEP"


def test_split_skills_points_at_the_skill_directory():
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        skill = root / "skills" / "example-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# example\n")
        (root / "CLAUDE.md").write_text("# house\n")
        bundles = _expand_dirs([str(root)], "skills")
        skill_bundles = [b for b in bundles if str(b[0]).endswith("example-skill")]
        assert skill_bundles
        path = skill_bundles[0][1]
        assert Path(path).name == "example-skill"
        assert (Path(path) / "SKILL.md").is_file()


if __name__ == "__main__":
    test_unpaired_cases_do_not_emit_keep()
    test_paired_delta_uses_shared_cases_only()
    test_split_skills_points_at_the_skill_directory()
    print("ok")
