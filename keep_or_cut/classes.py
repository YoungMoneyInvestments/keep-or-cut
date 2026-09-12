"""Split a Claude/Codex/Grok home into classes: claude.md, agents.md, skills, hooks, agents.

A user with a pile of skills does not want one delta for the whole pile.
They want to know which *kind* of context still earns tokens — and which
kinds newer models have outgrown.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SPLIT_MODES = ("auto", "off", "classes", "families", "skills")

_HOOK_CODE = {".py", ".js", ".mjs", ".cjs", ".sh", ".ts"}

# Default cap for one class dump. 0 = unlimited. A real ~/.claude skills tree
# can be millions of tokens if SKILL.md references are followed.
DEFAULT_CLASS_TOKEN_BUDGET = 24_000


@dataclass
class ContextClass:
    id: str
    kind: str
    label: str
    files: list[str] = field(default_factory=list)
    extra_notes: str = ""
    members: int = 0


def is_claude_home(root: str | Path) -> bool:
    """True for a Claude/Codex/Grok-style home, not only a CLAUDE.md tree."""
    path = Path(root).expanduser()
    if not path.is_dir():
        return False
    return (
        (path / "CLAUDE.md").is_file()
        or (path / "AGENTS.md").is_file()
        or (path / "skills").is_dir()
        or (path / "hooks").is_dir()
        or (path / "agents").is_dir()
    )


def estimate_tokens_from_files(root: Path, files: list[str], extra: str = "") -> int:
    n = len(extra)
    for rel in files:
        path = root / rel
        if path.is_file():
            try:
                n += path.stat().st_size
            except OSError:
                continue
    return n // 4


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
    out: list[str] = []
    for p in sorted(folder.rglob("*.md")):
        if not p.is_file():
            continue
        if not _path_stays_in_root(root, p) and p.name != "SKILL.md":
            continue
        out.append(str(p.relative_to(root)))
    return out


def _path_stays_in_root(root: Path, path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def _rel_skill_md(root: Path, skill_dir: Path) -> list[str]:
    """SKILL.md at the skill dir root only. Do not dump references/ or symlink targets."""
    skill = skill_dir / "SKILL.md"
    if skill.is_file():
        return [str(skill.relative_to(root))]
    return []


def _skill_blurb(skill_md: Path) -> str:
    try:
        text = skill_md.read_text(errors="replace")[:4000]
    except OSError:
        return "(unreadable)"
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end]
            match = re.search(r"^description:\s*[>|]?\s*(.+)$", block, re.M)
            if match:
                return match.group(1).strip().strip("\"'")[:200]
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("# ").strip()[:200]
    return "(no description)"


def _skill_inventory(skill_dirs: list[Path]) -> str:
    lines = [
        "# skills inventory",
        "SKILL.md dump exceeded the class token budget. Names and descriptions only.",
        "",
    ]
    for d in skill_dirs:
        skill = d / "SKILL.md"
        blurb = _skill_blurb(skill) if skill.is_file() else "(missing SKILL.md)"
        lines.append(f"- {d.name}: {blurb}")
    return "\n".join(lines) + "\n"


def _fit_budget(
    root: Path,
    files: list[str],
    extra: str,
    skill_dirs: list[Path],
    budget: int,
) -> tuple[list[str], str]:
    if budget <= 0:
        return files, extra
    if estimate_tokens_from_files(root, files, extra) <= budget:
        return files, extra
    inventory = _skill_inventory(skill_dirs)
    merged = "\n\n".join(part for part in (extra.strip(), inventory.strip()) if part)
    return [], merged + "\n"


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


def discover_classes(
    root: str | Path,
    mode: str = "classes",
    *,
    max_class_tokens: int = DEFAULT_CLASS_TOKEN_BUDGET,
) -> list[ContextClass]:
    """Return the classes to score for one --context-dir.

    classes  — claude.md / agents.md / skills / hooks / agents
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

    agents_md = path / "AGENTS.md"
    if agents_md.is_file():
        out.append(ContextClass("agents.md", "agents.md", "AGENTS.md", ["AGENTS.md"], members=1))

    skills_root = path / "skills"
    skill_dirs = sorted(p for p in skills_root.iterdir() if p.is_dir()) if skills_root.is_dir() else []
    skill_names = [p.name for p in skill_dirs]

    if mode == "classes" and skill_dirs:
        files: list[str] = []
        for d in skill_dirs:
            files.extend(_rel_skill_md(path, d))
        files, extra = _fit_budget(path, files, "", skill_dirs, max_class_tokens)
        out.append(
            ContextClass(
                "skills",
                "skills",
                f"skills ({len(skill_dirs)})",
                files,
                extra,
                members=len(skill_dirs),
            )
        )
    elif mode == "families" and skill_dirs:
        buckets: dict[str, list[Path]] = {}
        for d in skill_dirs:
            buckets.setdefault(skill_family(d.name, skill_names), []).append(d)
        for cid, dirs in sorted(buckets.items()):
            files = []
            for d in dirs:
                files.extend(_rel_skill_md(path, d))
            files, extra = _fit_budget(path, files, "", dirs, max_class_tokens)
            out.append(ContextClass(cid, "skills", cid, files, extra, members=len(dirs)))
    elif mode == "skills" and skill_dirs:
        for d in skill_dirs:
            files = _rel_skill_md(path, d)
            files, extra = _fit_budget(path, files, "", [d], max_class_tokens)
            out.append(ContextClass(f"skills/{d.name}", "skills", d.name, files, extra, members=1))

    hooks = path / "hooks"
    if hooks.is_dir():
        files = _rel_md(path, hooks)
        extra = _hook_inventory(hooks)
        if files or extra:
            out.append(ContextClass("hooks", "hooks", "hooks", files, extra, members=1))

    agents = path / "agents"
    agent_files = _rel_md(path, agents)
    if agent_files:
        out.append(ContextClass("agents", "agents", "agents", agent_files, members=len(agent_files)))

    return out
