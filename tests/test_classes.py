"""Discover claude.md / skills / hooks / agents as separate classes."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keep_or_cut.classes import discover_classes, is_claude_home, skill_family
from keep_or_cut.context import build_system_prompt
from keep_or_cut.leaderboard import class_matrix_markdown, to_markdown
from keep_or_cut.models import AblationDelta, Judgment, Profile
from keep_or_cut.profiles import default_profiles
from keep_or_cut.runner import run_one


def _tree(tmp: Path) -> Path:
    (tmp / "CLAUDE.md").write_text("# house rules\n")
    (tmp / "skills" / "example-skill").mkdir(parents=True)
    (tmp / "skills" / "example-skill" / "SKILL.md").write_text("# example-skill\n")
    (tmp / "skills" / "linting-audit").mkdir(parents=True)
    (tmp / "skills" / "linting-audit" / "SKILL.md").write_text("# audit\n")
    (tmp / "skills" / "linting-debug").mkdir(parents=True)
    (tmp / "skills" / "linting-debug" / "SKILL.md").write_text("# debug\n")
    (tmp / "hooks").mkdir()
    (tmp / "hooks" / "guard.py").write_text("print('hook')\n")
    (tmp / "agents").mkdir()
    (tmp / "agents" / "reviewer.md").write_text("# reviewer\n")
    return tmp


def test_is_claude_home_detects_typical_layout():
    with tempfile.TemporaryDirectory() as raw:
        root = _tree(Path(raw))
        assert is_claude_home(root)
    with tempfile.TemporaryDirectory() as raw:
        Path(raw, "persona.md").write_text("hi")
        assert not is_claude_home(Path(raw))


def test_discover_classes_splits_claude_home():
    with tempfile.TemporaryDirectory() as raw:
        root = _tree(Path(raw))
        classes = {c.id: c for c in discover_classes(root, "classes")}
        assert set(classes) == {"claude.md", "skills", "hooks", "agents"}
        assert classes["claude.md"].files == ["CLAUDE.md"]
        assert "skills/example-skill/SKILL.md" in classes["skills"].files
        assert classes["hooks"].kind == "hooks"
        assert "guard.py" in classes["hooks"].extra_notes
        assert classes["agents"].files == ["agents/reviewer.md"]


def test_discover_families_groups_shared_prefixes():
    with tempfile.TemporaryDirectory() as raw:
        root = _tree(Path(raw))
        ids = [c.id for c in discover_classes(root, "families")]
        assert "skills/linting" in ids
        assert "skills/example-skill" in ids
        assert "claude.md" in ids


def test_discover_skills_is_one_class_per_skill_dir():
    with tempfile.TemporaryDirectory() as raw:
        root = _tree(Path(raw))
        ids = [c.id for c in discover_classes(root, "skills")]
        assert "skills/example-skill" in ids
        assert "skills/linting-audit" in ids
        assert "skills/linting-debug" in ids


def test_skill_family_needs_two_to_group():
    names = ["example-skill", "linting-audit", "linting-debug"]
    assert skill_family("linting-audit", names) == "skills/linting"
    assert skill_family("example-skill", names) == "skills/example-skill"


def test_build_system_prompt_honors_include_and_extra_notes():
    with tempfile.TemporaryDirectory() as raw:
        root = _tree(Path(raw))
        notes = build_system_prompt(str(root), include=("CLAUDE.md",))
        assert "house rules" in notes
        assert "example-skill" not in notes
        mixed = build_system_prompt(
            str(root),
            include=("CLAUDE.md",),
            extra_notes="# hooks inventory\n- guard.py\n",
        )
        assert "guard.py" in mixed


def test_class_matrix_lists_models_across_classes():
    deltas = [
        AblationDelta("claude-haiku-4-5-20251001", "hooks", 8.0, 8.5, 0.5, "PROMPT_BLOAT", kind="hooks"),
        AblationDelta("claude-sonnet-5", "hooks", 8.0, 7.6, -0.4, "PROMPT_BLOAT", kind="hooks"),
        AblationDelta("claude-opus-5", "hooks", 8.0, 6.5, -1.5, "REMOVE", kind="hooks"),
        AblationDelta("claude-opus-5", "skills", 8.0, 9.6, 1.6, "KEEP", kind="skills"),
    ]
    table = class_matrix_markdown(deltas)
    assert "hooks" in table
    assert "fading" in table.lower() or "models need it less" in table.lower()
    assert "REMOVE" in table
    md = to_markdown(
        [Judgment("c1", "p", 7, "ok", "j")],
        deltas,
    )
    assert "Which classes still earn tokens" in md


def test_default_profiles_can_carry_class_include():
    profiles = default_profiles(
        context_dirs=[("hooks", "/tmp/fake", ("hooks/README.md",), "# hooks\n", "hooks", "hooks")],
        models=[("anthropic", "claude-opus-5")],
        provider="anthropic",
        include_bare=True,
    )
    assert profiles[1].class_id == "hooks"
    assert profiles[1].include == ("hooks/README.md",)


if __name__ == "__main__":
    test_is_claude_home_detects_typical_layout()
    test_discover_classes_splits_claude_home()
    test_discover_families_groups_shared_prefixes()
    test_discover_skills_is_one_class_per_skill_dir()
    test_skill_family_needs_two_to_group()
    test_build_system_prompt_honors_include_and_extra_notes()
    test_class_matrix_lists_models_across_classes()
    test_default_profiles_can_carry_class_include()
    print("ok")
