"""Split a Claude home into classes: claude.md, skills, hooks, agents.

A user with a pile of skills does not want one delta for the whole pile.
They want to know which *kind* of context still earns tokens — and which
kinds newer models have outgrown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SPLIT_MODES = ("auto", "off", "classes", "families", "skills")

_HOOK_CODE = {".py", ".js", ".mjs", ".cjs", ".sh", ".ts"}


@dataclass
class ContextClass:
    id: str
    kind: str
    label: str
    files: list[str] = field(default_factory=list)
    extra_notes: str = ""
    members: int = 0


def is_claude_home(root: str | Path) -> bool:
    path = Path(root).expanduser()
    if not path.is_dir():
        return False
    return (
        (path / "CLAUDE.md").is_file()
        or (path / "skills").is_dir()
        or (path / "hooks").is_dir()
        or (path / "agents").is_dir()
    )


def skill_family(name: str, names: list[str]) -> str:
    """Group example-audit + example-debug → skills/example.

    A prefix only groups when at least two skill dirs share it.
    """
    prefix = name.split("-", 1)[0]
    if prefix and sum(1 for n in names if n == prefix or n.startswith(prefix + "-")) >= 2:
        return f"skills/{prefix}"
    return f"skills/{name}"


def _rel_md(root: Path, folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return [str(p.relative_to(root)) for p in sorted(folder.rglob("*.md")) if p.is_file()]


def _hook_inventory(hooks: Path) -> str:
    names = []
    for p in sorted(hooks.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in _HOOK_CODE:
            continue
        if "__pycache__" in p.parts or p.name.startswith("."):
            continue
        names.append(str(p.relative_to(hooks)))
    if not names:
        return ""
    lines = ["# hooks inventory", "These hook files are installed. They are not executed in this bench.", ""]
    lines.extend(f"- {n}" for n in names)
    return "\n".join(lines) + "\n"


def discover_classes(root: str | Path, mode: str = "classes") -> list[ContextClass]:
    """Return the classes to score for one --context-dir.

    classes  — claude.md / skills / hooks / agents
    families — same, but skills split by shared name prefix
    skills   — same, but one class per skill directory
    """
    if mode in ("off", "auto"):
        return []
    path = Path(root).expanduser()
    if not path.is_dir() or not is_claude_home(path):
        return []

    out: list[ContextClass] = []

    claude = path / "CLAUDE.md"
    if claude.is_file():
        out.append(ContextClass("claude.md", "claude.md", "CLAUDE.md", ["CLAUDE.md"], members=1))

    skills_root = path / "skills"
    skill_dirs = sorted(p for p in skills_root.iterdir() if p.is_dir()) if skills_root.is_dir() else []
    skill_names = [p.name for p in skill_dirs]

    if mode == "classes" and skill_dirs:
        files: list[str] = []
        for d in skill_dirs:
            files.extend(_rel_md(path, d))
        out.append(
            ContextClass("skills", "skills", f"skills ({len(skill_dirs)})", files, members=len(skill_dirs))
        )
    elif mode == "families" and skill_dirs:
        buckets: dict[str, list[Path]] = {}
        for d in skill_dirs:
            buckets.setdefault(skill_family(d.name, skill_names), []).append(d)
        for cid, dirs in sorted(buckets.items()):
            files = []
            for d in dirs:
                files.extend(_rel_md(path, d))
            out.append(ContextClass(cid, "skills", cid, files, members=len(dirs)))
    elif mode == "skills" and skill_dirs:
        for d in skill_dirs:
            files = _rel_md(path, d)
            out.append(ContextClass(f"skills/{d.name}", "skills", d.name, files, members=1))

    hooks = path / "hooks"
    if hooks.is_dir():
        files = _rel_md(path, hooks)
        extra = "" if files else _hook_inventory(hooks)
        if files or extra:
            out.append(ContextClass("hooks", "hooks", "hooks", files, extra, members=1))

    agents = path / "agents"
    agent_files = _rel_md(path, agents)
    if agent_files:
        out.append(ContextClass("agents", "agents", "agents", agent_files, members=len(agent_files)))

    return out
