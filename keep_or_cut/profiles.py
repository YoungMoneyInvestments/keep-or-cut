"""Profile matrix: each Model crossed with bare plus one or more Context Bundles."""
from __future__ import annotations

from pathlib import Path

from keep_or_cut.models import Profile

HARNESS_MODES = ("auto", "notes", "skill")

_MODELS = [
    ("anthropic", "claude-opus-5"),
    ("anthropic", "claude-sonnet-5"),
    ("anthropic", "claude-haiku-4-5-20251001"),
]

MODEL_ALIASES = {
    "opus": ("anthropic", "claude-opus-5"),
    "sonnet": ("anthropic", "claude-sonnet-5"),
    "haiku": ("anthropic", "claude-haiku-4-5-20251001"),
    "claude-opus-5": ("anthropic", "claude-opus-5"),
    "claude-sonnet-5": ("anthropic", "claude-sonnet-5"),
    "claude-haiku-4-5-20251001": ("anthropic", "claude-haiku-4-5-20251001"),
    "grok": ("grok", "grok-4.6"),
    "codex": ("codex", "gpt-5.6-luna"),
    "cursor": ("cursor", "auto"),
    "gemini": ("gemini", "gemini-3.6-flash-high"),
}


def resolve_models(spec: str) -> list[tuple[str, str]]:
    """Parse 'opus,sonnet' or 'anthropic:claude-opus-5,xai:grok-4' into (provider, model) pairs."""
    out: list[tuple[str, str]] = []
    for raw in spec.split(","):
        token = raw.strip()
        if not token:
            continue
        if token in MODEL_ALIASES:
            out.append(MODEL_ALIASES[token])
        elif ":" in token:
            provider, model = token.split(":", 1)
            out.append((provider.strip(), model.strip()))
        else:
            aliases = ", ".join(sorted(MODEL_ALIASES))
            raise ValueError(
                f"unknown model '{token}'. Use {aliases}, or provider:model-id"
            )
    if not out:
        raise ValueError("no models specified")
    return out


def label_for_context_dir(context_dir: str) -> str:
    path = Path(context_dir).expanduser()
    return path.name or "context"


def _normalize_bundle(entry: tuple) -> tuple[str, str, tuple[str, ...] | None, str, str, str]:
    """Accept (label, path) or the longer class tuple from --split."""
    if len(entry) == 2:
        label, path = entry
        return label, path, None, "", "", ""
    if len(entry) == 6:
        label, path, include, extra, class_id, kind = entry
        return label, path, include, extra, class_id, kind
    raise ValueError(f"context dir entry must be 2 or 6 fields, got {len(entry)}")


def default_profiles(
    *,
    context_dirs: list[tuple] | None = None,
    models: list[tuple[str, str]] | None = None,
    provider: str | None = None,
    include_bare: bool = True,
    harness: str = "auto",
) -> list[Profile]:
    """Build the Profile matrix.

    context_dirs: list of (label, path) or
    (label, path, include, extra_notes, class_id, kind).
    None → the synthetic examples/context demo.
    provider: "auto" / None uses subscription CLIs. Ambient API keys never change that.
    harness: auto=skill dirs use slash invoke; notes=always system-prompt wrap;
    skill=require skill dirs with SKILL.md.
    """
    if harness not in HARNESS_MODES:
        raise ValueError(f"unknown harness mode: {harness}")
    if models is None:
        models = list(_MODELS)
    if context_dirs is None:
        context_dirs = [("example", "examples/context")]

    explicit_provider = provider if provider not in (None, "auto") else None

    profiles: list[Profile] = []
    for src_provider, model in models:
        if explicit_provider:
            effective = explicit_provider
        elif src_provider == "anthropic":
            effective = "cli"
        else:
            effective = src_provider
        if include_bare:
            profiles.append(
                Profile(id=f"{model}+bare", provider=effective, model=model, context_dir=None)
            )
        for entry in context_dirs:
            label, context_dir, include, extra, class_id, kind = _normalize_bundle(entry)
            skill_name = ""
            if harness != "notes":
                from keep_or_cut.context import detect_skill_name

                detected = detect_skill_name(context_dir)
                if harness == "skill" and not detected:
                    raise ValueError(
                        f"--harness skill requires a skill dir with SKILL.md at its root: "
                        f"{context_dir}"
                    )
                skill_name = detected or ""
            profiles.append(
                Profile(
                    id=f"{model}+{label}",
                    provider=effective,
                    model=model,
                    context_dir=context_dir,
                    include=include,
                    extra_notes=extra,
                    class_id=class_id,
                    kind=kind,
                    skill_name=skill_name,
                )
            )
    return profiles
