"""Core dataclasses for keep_or_cut benchmarks and skill ablation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Case:
    id: str
    category: str
    prompt: str
    rubric: list[str]


@dataclass
class Profile:
    id: str
    provider: str  # "anthropic" | "xai" | "openai" | "omniroute"
    model: str  # provider-specific model id
    context_dir: str | None  # None => bare (empty system prompt)
    include: tuple[str, ...] | None = None  # relative paths; None = every *.md
    extra_notes: str = ""
    class_id: str = ""
    kind: str = ""
    skill_name: str = ""  # non-empty => slash-invoke via claude -p /{skill_name}


@dataclass
class Run:
    case_id: str
    profile_id: str
    output: str
    latency_s: float
    input_tokens: int
    output_tokens: int
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class Judgment:
    case_id: str
    profile_id: str
    score: int  # 1-10
    reasoning: str
    judge_model: str


@dataclass
class AblationDelta:
    model: str
    skill_name: str
    bare_score: float
    with_skill_score: float
    delta: float
    recommendation: str  # "KEEP" | "PROMPT_BLOAT" | "REMOVE"
    kind: str = ""
    n_paired: int = 0
