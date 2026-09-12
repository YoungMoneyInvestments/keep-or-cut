"""Real-home class split: +all, SKILL.md-only, hooks inventory, AGENTS.md, budget."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keep_or_cut.classes import discover_classes, is_claude_home
from keep_or_cut.cli import _expand_dirs
from keep_or_cut.context import build_system_prompt


def _home(tmp: Path, *, claude: bool = True, agents_md: bool = False) -> Path:
    if claude:
        (tmp / "CLAUDE.md").write_text("# house rules\n")
    if agents_md:
        (tmp / "AGENTS.md").write_text("# agent rules\n")
    skill = tmp / "skills" / "example-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# example-skill\nDo the task.\n")
    (skill / "NOTES.md").write_text("# extra notes that must not dump\n")
    (tmp / "hooks").mkdir()
    (tmp / "hooks" / "guard.py").write_text("print('hook')\n")
    (tmp / "hooks" / "README.md").write_text("# hook readme\n")
    (tmp / "agents").mkdir()
    (tmp / "agents" / "reviewer.md").write_text("# reviewer\n")
    (tmp / "plugins" / "cache").mkdir(parents=True)
    (tmp / "plugins" / "cache" / "PLUGIN.md").write_text("# plugin noise\n")
    (tmp / "jobs").mkdir()
    (tmp / "jobs" / "log.md").write_text("# job log\n")
    return tmp


def test_is_claude_home_detects_agents_md_without_claude_md():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "AGENTS.md").write_text("# agents\n")
        assert is_claude_home(root)
    with tempfile.TemporaryDirectory() as raw:
        Path(raw, "persona.md").write_text("hi")
        assert not is_claude_home(Path(raw))


def test_discover_classes_includes_agents_md():
    with tempfile.TemporaryDirectory() as raw:
        root = _home(Path(raw), claude=False, agents_md=True)
        classes = {c.id: c for c in discover_classes(root, "classes")}
        assert "agents.md" in classes
        assert "claude.md" not in classes
        assert classes["agents.md"].files == ["AGENTS.md"]


def test_skills_class_is_skill_md_only():
    with tempfile.TemporaryDirectory() as raw:
        root = _home(Path(raw))
        classes = {c.id: c for c in discover_classes(root, "classes")}
        files = classes["skills"].files
        assert files == ["skills/example-skill/SKILL.md"]
        assert not any("NOTES.md" in f for f in files)


def test_skills_class_does_not_dump_symlink_target():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "CLAUDE.md").write_text("# rules\n")
        outside = root / "outside-target"
        outside.mkdir()
        (outside / "SKILL.md").write_text("# linked-skill\n")
        (outside / "DUMP.md").write_text("# huge dump\n" + ("noise " * 1000))
        skills = root / "skills"
        skills.mkdir()
        (skills / "linked-skill").symlink_to(outside)
        classes = {c.id: c for c in discover_classes(root, "classes")}
        files = classes["skills"].files
        assert files == ["skills/linked-skill/SKILL.md"]
        notes = build_system_prompt(str(root), include=tuple(files))
        assert "linked-skill" in notes
        assert "huge dump" not in notes


def test_hooks_inventory_attached_even_when_markdown_exists():
    with tempfile.TemporaryDirectory() as raw:
        root = _home(Path(raw))
        classes = {c.id: c for c in discover_classes(root, "classes")}
        hooks = classes["hooks"]
        assert "hooks/README.md" in hooks.files
        assert "guard.py" in hooks.extra_notes
        assert "not executed" in hooks.extra_notes


def test_plus_all_is_union_of_classes_not_home_rglob():
    with tempfile.TemporaryDirectory() as raw:
        root = _home(Path(raw))
        bundles = _expand_dirs([str(root)], "classes")
        plus_all = next(b for b in bundles if b[0].endswith("+all"))
        assert len(plus_all) == 6
        _label, path, include, extra, _class_id, kind = plus_all
        assert path == str(root)
        assert include is not None
        assert "CLAUDE.md" in include
        assert "skills/example-skill/SKILL.md" in include
        assert "hooks/README.md" in include
        assert "agents/reviewer.md" in include
        assert not any("PLUGIN.md" in f for f in include)
        assert not any("NOTES.md" in f for f in include)
        assert not any(f.startswith("jobs/") for f in include)
        assert "guard.py" in extra
        assert kind == "bundle"
        dumped = build_system_prompt(path, include=include, extra_notes=extra)
        assert "plugin noise" not in dumped
        assert "job log" not in dumped


def test_split_off_rglob_skips_plugins_jobs_cache():
    with tempfile.TemporaryDirectory() as raw:
        root = _home(Path(raw))
        notes = build_system_prompt(str(root))
        assert "house rules" in notes
        assert "plugin noise" not in notes
        assert "job log" not in notes


def test_over_budget_skills_class_falls_back_to_inventory():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "CLAUDE.md").write_text("# rules\n")
        skill = root / "skills" / "example-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# example-skill\n" + ("word " * 20000))
        classes = {c.id: c for c in discover_classes(root, "classes", max_class_tokens=500)}
        skills = classes["skills"]
        assert skills.files == []
        assert "example-skill" in skills.extra_notes
        assert "inventory" in skills.extra_notes.lower()
