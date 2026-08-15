from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from keep_or_cut.ablation import analyze_deltas
from keep_or_cut.cases import load_cases
from keep_or_cut.classes import SPLIT_MODES, discover_classes, is_claude_home
from keep_or_cut.context import WRAP_MODES, bundle_skill_files
from keep_or_cut.dashboard import write_dashboard
from keep_or_cut.leaderboard import to_markdown

try:
    from keep_or_cut.elo import bootstrap_delta_ci, elo_ratings
except ImportError:  # Elo shipped in a parallel change; class split must run without it
    bootstrap_delta_ci = None
    elo_ratings = None
from keep_or_cut.profiles import HARNESS_MODES, default_profiles, label_for_context_dir, resolve_models
from keep_or_cut.runner import run_all, runs_to_dicts
from keep_or_cut.judge import judge_all, judgments_to_dicts


def _expand_dirs(paths: list[str], split: str) -> list[tuple]:
    """Turn --context-dir paths into profile bundles. Auto-splits a Claude home."""
    bundles: list[tuple] = []
    for path in paths:
        mode = split
        if mode == "auto":
            mode = "classes" if is_claude_home(path) else "off"
        classes = discover_classes(path, mode) if mode != "off" else []
        if not classes:
            bundles.append((label_for_context_dir(path), path))
            continue
        print(
            f"[cli] {path} split into {len(classes)} classes: "
            + ", ".join(c.id for c in classes)
            + " (plus +all for the whole pile). --split off to disable."
        )
        bundles.append((label_for_context_dir(path) + "+all", path))
        for cls in classes:
            include = tuple(cls.files)
            if not include and not cls.extra_notes:
                continue
            cls_path = path
            if mode == "skills" and cls.kind == "skills":
                skill_dir = Path(path).expanduser() / "skills" / Path(cls.id).name
                if (skill_dir / "SKILL.md").is_file():
                    cls_path = str(skill_dir)
                    include = None
            bundles.append(
                (cls.id, cls_path, include, cls.extra_notes, cls.id, cls.kind)
            )
    return bundles


def main() -> None:
    p = argparse.ArgumentParser(
        prog="keep_or_cut",
        description="Score whether a context bundle helps a model, or just gets in the way.",
    )
    p.add_argument("--cases-dir", default="cases")
    p.add_argument("--out-dir", default="results")
    p.add_argument(
        "--context-dir",
        action="append",
        default=None,
        metavar="PATH",
        help="Context Bundle to test against bare. Repeatable. Default: examples/context",
    )
    p.add_argument(
        "--harness",
        choices=HARNESS_MODES,
        default="auto",
        help="auto=skill dirs use slash /skill invoke; notes=always system-prompt wrap; "
        "skill=require --context-dir to be skill dirs with SKILL.md.",
    )
    p.add_argument(
        "--wrap",
        choices=WRAP_MODES,
        default="fair",
        help="How to attach the bundle. fair=default (task is the user message). "
        "system=notes as raw system prompt. raw=reproduce the old System-Instructions wrap.",
    )
    p.add_argument(
        "--models",
        default="opus,sonnet,haiku",
        help="Comma list of aliases (opus,sonnet,haiku,grok,codex,cursor,gemini) "
        "or provider:model-id",
    )
    p.add_argument(
        "--provider",
        default="auto",
        help="auto=subscription CLIs (claude/codex/grok/cursor/gemini). Never switches "
        "to billed API because a key is in the environment. Use "
        "--provider anthropic/openai/xai for APIs.",
    )
    p.add_argument(
        "--split",
        choices=SPLIT_MODES,
        default="auto",
        help="auto=split a Claude home (CLAUDE.md/skills/hooks/agents) into classes. "
        "classes=those four kinds. families=group skills by name prefix. "
        "skills=one profile per skill dir. off=one blob for the whole dir.",
    )
    p.add_argument("--no-bare", action="store_true", help="skip the bare (no extra bundle) arm")
    p.add_argument("--smoke", action="store_true", help="first case × first model only")
    p.add_argument("--judge-provider", default=None)
    p.add_argument("--judge-model", default="claude-opus-5")
    p.add_argument("--no-judge", action="store_true", help="run only, skip scoring")
    args = p.parse_args()

    cases = load_cases(args.cases_dir)
    if not cases:
        raise SystemExit(f"no cases found in {args.cases_dir}")

    try:
        models = resolve_models(args.models)
    except ValueError as e:
        raise SystemExit(str(e)) from e

    if args.context_dir:
        context_dirs = _expand_dirs(args.context_dir, args.split)
    else:
        context_dirs = None

    if args.smoke:
        cases = cases[:1]
        models = models[:1]

    try:
        profiles = default_profiles(
            context_dirs=context_dirs,
            models=models,
            provider=args.provider,
            include_bare=not args.no_bare,
            harness=args.harness,
        )
    except ValueError as e:
        raise SystemExit(str(e)) from e
    if not profiles:
        raise SystemExit("no profiles to run (did you pass --no-bare with no --context-dir?)")

    skill_profiles = [p for p in profiles if p.skill_name]
    notes_only_skill_hits = []
    if args.harness == "notes":
        for profile in profiles:
            for rel in bundle_skill_files(profile.context_dir):
                notes_only_skill_hits.append(f"{profile.id}:{rel}")
    if notes_only_skill_hits:
        print(
            "[cli] note: --harness notes dumps SKILL.md into the system prompt. "
            "That is not a Claude Code skill-invocation test and may trigger refusals "
            "(issue #1). Use --harness auto or --harness skill for slash invoke."
        )
    elif skill_profiles:
        names = ", ".join(sorted({p.skill_name for p in skill_profiles}))
        print(f"[cli] skill harness active for: {names} (slash invoke via claude -p)")

    judge_provider = args.judge_provider or "cli"

    runs = run_all(cases, profiles, wrap=args.wrap)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_path = out_dir / f"runs_{ts}.json"
    run_path.write_text(json.dumps(runs_to_dicts(runs), indent=2))
    print(f"[cli] wrote {run_path}")

    expected = len(cases) * len(profiles)
    failed = [r for r in runs if r.error]
    homes = args.context_dir or ["examples/context"]
    dash_kw = dict(
        out_path=out_dir / "dashboard.html",
        profiles=profiles,
        home=homes[0],
        n_cases=len(cases),
    )

    if len(runs) != expected or failed:
        missing: list[str] = []
        have = {(r.case_id, r.profile_id) for r in runs}
        for case in cases:
            for profile in profiles:
                if (case.id, profile.id) not in have:
                    missing.append(f"{case.id} × {profile.id}")
        for run in failed:
            missing.append(f"{run.case_id} × {run.profile_id}: {run.error}")
        dash = write_dashboard(None, status="incomplete", missing=missing, **dash_kw)
        print(
            f"[cli] incomplete matrix: {len(runs)}/{expected} cells, "
            f"{len(failed)} failed. No KEEP/REMOVE leaderboard."
        )
        print(f"[cli] wrote {dash}")
        raise SystemExit(2)

    if args.no_judge:
        return

    cases_by_id = {c.id: c for c in cases}
    judgments = judge_all(runs, cases_by_id, judge_provider, args.judge_model)
    judged_path = out_dir / f"judged_{ts}.json"
    judged_path.write_text(json.dumps(judgments_to_dicts(judgments), indent=2))
    print(f"[cli] wrote {judged_path}")

    deltas = analyze_deltas(judgments, profiles)
    elo = elo_ratings(judgments) if elo_ratings else None
    delta_ci = bootstrap_delta_ci(judgments, profiles) if bootstrap_delta_ci else None
    board = to_markdown(judgments, deltas, elo=elo, delta_ci=delta_ci or None)
    board_path = out_dir / f"leaderboard_{ts}.md"
    board_path.write_text(board + "\n")
    status = "complete" if deltas else "unpaired"
    dash = write_dashboard(board_path, deltas=deltas, status=status, **dash_kw)
    print(f"[cli] wrote {board_path}\n\n{board}")
    print(f"[cli] wrote {dash}")


if __name__ == "__main__":
    main()
