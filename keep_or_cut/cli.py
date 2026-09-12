from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from keep_or_cut.ablation import analyze_deltas
from keep_or_cut.cases import load_cases
from keep_or_cut.classes import (
    DEFAULT_CLASS_TOKEN_BUDGET,
    SPLIT_MODES,
    discover_classes,
    estimate_tokens_from_files,
    is_claude_home,
)
from keep_or_cut.context import WRAP_MODES, bundle_skill_files
from keep_or_cut.dashboard import write_dashboard
from keep_or_cut.leaderboard import to_markdown

try:
    from keep_or_cut.elo import bootstrap_delta_ci, elo_ratings
except ImportError:  # Elo shipped in a parallel change; class split must run without it
    bootstrap_delta_ci = None
    elo_ratings = None
from keep_or_cut.profiles import HARNESS_MODES, default_profiles, label_for_context_dir, resolve_models
from keep_or_cut.runner import is_policy_skip, run_all, runs_from_dicts, runs_to_dicts
from keep_or_cut.judge import judge_all, judgments_to_dicts
from keep_or_cut.models import Case, Judgment, Profile

_SECONDS_PER_CELL = 20
_PROVIDER_BINS = {
    "cli": ("claude",),
    "grok": ("grok",),
    "codex": ("codex",),
    "cursor": ("cursor-agent",),
    "gemini": ("gmi", "gemini"),
}

_EPILOG = """
Examples:
  keep-or-cut --smoke
  keep-or-cut --list --context-dir ~/.claude
  keep-or-cut --context-dir ~/.claude --models haiku
  keep-or-cut --resume results/runs_YYYYMMDDThhmmssZ.json --context-dir ~/.claude

Start with --smoke, then --list, then one model. A full home × many models is slow.
+all is the union of discovered classes, not plugins/jobs/cache.
"""


def _expand_dirs(
    paths: list[str],
    split: str,
    *,
    max_class_tokens: int = DEFAULT_CLASS_TOKEN_BUDGET,
    quiet: bool = False,
) -> list[tuple]:
    """Turn --context-dir paths into profile bundles. Auto-splits a Claude/Codex/Grok home."""
    bundles: list[tuple] = []
    for path in paths:
        root = Path(path).expanduser()
        if not root.is_dir():
            raise FileNotFoundError(path)
        mode = split
        if mode == "auto":
            mode = "classes" if is_claude_home(root) else "off"
        classes = (
            discover_classes(root, mode, max_class_tokens=max_class_tokens)
            if mode != "off"
            else []
        )
        if not classes:
            bundles.append((label_for_context_dir(path), path))
            continue
        if not quiet:
            print(
                f"[cli] {path} split into {len(classes)} classes: "
                + ", ".join(c.id for c in classes)
                + " (plus +all = union of those classes, not plugins/cache). --split off to disable."
            )
        all_files: list[str] = []
        extras: list[str] = []
        seen: set[str] = set()
        for cls in classes:
            for rel in cls.files:
                if rel not in seen:
                    seen.add(rel)
                    all_files.append(rel)
            if cls.extra_notes.strip():
                extras.append(cls.extra_notes.strip())
        bundles.append(
            (
                label_for_context_dir(path) + "+all",
                path,
                tuple(all_files),
                "\n\n".join(extras),
                label_for_context_dir(path) + "+all",
                "bundle",
            )
        )
        for cls in classes:
            include = tuple(cls.files)
            if not include and not cls.extra_notes:
                continue
            cls_path = path
            if mode == "skills" and cls.kind == "skills":
                skill_dir = root / "skills" / Path(cls.id).name
                if (skill_dir / "SKILL.md").is_file():
                    cls_path = str(skill_dir)
                    include = ("SKILL.md",)
            bundles.append(
                (cls.id, cls_path, include, cls.extra_notes, cls.id, cls.kind)
            )
    return bundles


def _print_plan(
    *,
    homes: list[str],
    split: str,
    cases: list[Case],
    models: list[tuple[str, str]],
    profiles: list[Profile],
    max_class_tokens: int,
) -> None:
    print("keep-or-cut plan")
    for home in homes:
        root = Path(home).expanduser()
        mode = split
        if mode == "auto":
            mode = "classes" if is_claude_home(root) else "off"
        print(f"  home: {root}")
        print(f"  split: {mode}")
        if mode == "off" or not root.is_dir():
            continue
        classes = discover_classes(root, mode, max_class_tokens=max_class_tokens)
        if not classes:
            print("  classes: (none — whole dir as one blob)")
            continue
        print("  classes:")
        for cls in classes:
            tokens = estimate_tokens_from_files(root, cls.files, cls.extra_notes)
            nfiles = len(cls.files)
            extra = "  inventory" if cls.files == [] and cls.extra_notes else ""
            print(f"    {cls.id:<16} {nfiles} file{'s' if nfiles != 1 else ''}  ~{tokens} tokens{extra}")
        all_files: list[str] = []
        seen: set[str] = set()
        extras = []
        for cls in classes:
            for rel in cls.files:
                if rel not in seen:
                    seen.add(rel)
                    all_files.append(rel)
            if cls.extra_notes.strip():
                extras.append(cls.extra_notes.strip())
        all_tokens = estimate_tokens_from_files(root, all_files, "\n\n".join(extras))
        print(f"    {'+all':<16} {len(all_files)} files  ~{all_tokens} tokens  (union of classes)")
    print(f"  models: {', '.join(m for _, m in models)}")
    print(f"  cases: {len(cases)}")
    print(f"  profiles: {len(profiles)}")
    cells = len(cases) * len(profiles)
    print(f"  cells: {cells}")
    minutes = max(1, (cells * _SECONDS_PER_CELL + 59) // 60)
    print(f"  estimate: ~{minutes} min at ~{_SECONDS_PER_CELL}s/cell (smoke is the cheap check)")
    print("  next: keep-or-cut --smoke --context-dir PATH")


def _preflight(profiles: list[Profile]) -> list[str]:
    warnings: list[str] = []
    for provider in sorted({p.provider for p in profiles}):
        names = _PROVIDER_BINS.get(provider)
        if not names:
            continue
        if not any(shutil.which(name) for name in names):
            warnings.append(
                f"no binary for provider {provider} ({' / '.join(names)}). Those cells will fail."
            )
    return warnings


def _load_resume(path: str) -> list:
    resume_path = Path(path).expanduser()
    if not resume_path.is_file():
        raise SystemExit(f"resume file not found: {path}")
    try:
        rows = json.loads(resume_path.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(f"resume file is not JSON: {path} ({e})") from e
    if not isinstance(rows, list):
        raise SystemExit(f"resume file must be a list of runs: {path}")
    return runs_from_dicts(rows)


def unusable_judge_cells(
    judgments: list[Judgment],
    cases: list[Case],
    profiles: list[Profile],
) -> list[str]:
    """Case × Profile labels that are missing or have an unusable score (≤ 0)."""
    missing: list[str] = []
    have = {(j.case_id, j.profile_id) for j in judgments}
    for case in cases:
        for profile in profiles:
            if (case.id, profile.id) not in have:
                missing.append(f"{case.id} × {profile.id}")
    for judgment in judgments:
        if judgment.score <= 0:
            missing.append(f"{judgment.case_id} × {judgment.profile_id}: {judgment.reasoning}")
    return missing


def main() -> None:
    p = argparse.ArgumentParser(
        prog="keep-or-cut",
        description="Score whether a context bundle helps a model, or just gets in the way.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        help="auto=split a Claude/Codex/Grok home (CLAUDE.md or AGENTS.md / skills / "
        "hooks / agents) into classes. classes=those kinds. families=group skills by "
        "name prefix. skills=one profile per skill dir. off=one blob for the whole dir.",
    )
    p.add_argument("--no-bare", action="store_true", help="skip the bare (no extra bundle) arm")
    p.add_argument("--smoke", action="store_true", help="first case × first model only")
    p.add_argument("--list", action="store_true", help="print the split, token estimates, and cell count, then exit")
    p.add_argument("--dry-run", action="store_true", help="print the profile matrix, then exit")
    p.add_argument("--resume", default=None, metavar="RUNS_JSON", help="reuse completed cells from a prior runs_*.json")
    p.add_argument(
        "--max-class-tokens",
        type=int,
        default=DEFAULT_CLASS_TOKEN_BUDGET,
        help="cap one class dump (default 24000). 0 = unlimited. Over budget → name+description inventory.",
    )
    p.add_argument(
        "--strict-matrix",
        action="store_true",
        help="fail-close KEEP/REMOVE if any cell is unusable, including provider policy skips",
    )
    p.add_argument("--judge-provider", default=None)
    p.add_argument("--judge-model", default="claude-opus-5")
    p.add_argument("--no-judge", action="store_true", help="run only, skip scoring")
    args = p.parse_args()

    cases_root = Path(args.cases_dir)
    if not cases_root.is_dir():
        print(
            f"no cases found: {args.cases_dir} is not a directory.\n"
            "Run from the keep-or-cut repo root, or pass --cases-dir.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        cases = load_cases(args.cases_dir)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2) from e
    if not cases:
        print(f"no cases found in {args.cases_dir}", file=sys.stderr)
        raise SystemExit(2)

    try:
        models = resolve_models(args.models)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2) from e

    try:
        if args.context_dir:
            context_dirs = _expand_dirs(
                args.context_dir,
                args.split,
                max_class_tokens=args.max_class_tokens,
                quiet=args.list or args.dry_run,
            )
        else:
            context_dirs = None
    except FileNotFoundError as e:
        print(
            f"context dir not found: {e}\n"
            f"Looked at {Path(str(e)).expanduser()}\n"
            "Pass an existing directory, or omit --context-dir to use examples/context.",
            file=sys.stderr,
        )
        raise SystemExit(2) from e

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
        print(str(e), file=sys.stderr)
        raise SystemExit(2) from e
    if not profiles:
        print("no profiles to run (did you pass --no-bare with no --context-dir?)", file=sys.stderr)
        raise SystemExit(2)

    homes = args.context_dir or ["examples/context"]
    if args.list or args.dry_run:
        _print_plan(
            homes=homes,
            split=args.split,
            cases=cases,
            models=models,
            profiles=profiles,
            max_class_tokens=args.max_class_tokens,
        )
        if args.dry_run:
            print("  profile ids:")
            for profile in profiles:
                print(f"    {profile.id}")
        raise SystemExit(0)

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

    for warning in _preflight(profiles):
        print(f"[cli] warn: {warning}")

    existing = _load_resume(args.resume) if args.resume else None
    judge_provider = args.judge_provider or "cli"

    runs = run_all(cases, profiles, wrap=args.wrap, existing=existing)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_path = out_dir / f"runs_{ts}.json"
    run_path.write_text(json.dumps(runs_to_dicts(runs), indent=2))
    print(f"[cli] wrote {run_path}")

    expected = len(cases) * len(profiles)
    failed = [r for r in runs if r.error]
    policy_failed = [r for r in failed if is_policy_skip(r.error)]
    dash_kw = dict(
        out_path=out_dir / "dashboard.html",
        profiles=profiles,
        home=homes[0],
        n_cases=len(cases),
    )
    dropped: list[str] = []

    if policy_failed and not args.strict_matrix:
        by_id = {p.id: p for p in profiles}
        skipped_models = {
            by_id[r.profile_id].model for r in policy_failed if r.profile_id in by_id
        }
        if skipped_models:
            dropped = sorted(skipped_models)
            print(
                f"[cli] dropped {', '.join(dropped)}: provider policy skip. "
                "KEEP/REMOVE uses remaining models. Re-run with --strict-matrix to fail-close instead."
            )
            profiles = [p for p in profiles if p.model not in skipped_models]
            keep_ids = {p.id for p in profiles}
            runs = [r for r in runs if r.profile_id in keep_ids]
            failed = [r for r in runs if r.error]
            expected = len(cases) * len(profiles)
            dash_kw["profiles"] = profiles

    if not profiles or len(runs) != expected or failed:
        missing: list[str] = []
        have = {(r.case_id, r.profile_id) for r in runs}
        for case in cases:
            for profile in profiles:
                if (case.id, profile.id) not in have:
                    missing.append(f"{case.id} × {profile.id}")
        for run in failed:
            missing.append(f"{run.case_id} × {run.profile_id}: {run.error}")
        if args.strict_matrix:
            for run in policy_failed:
                label = f"{run.case_id} × {run.profile_id}: {run.error}"
                if label not in missing:
                    missing.append(label)
        if missing or not profiles:
            dash = write_dashboard(None, status="incomplete", missing=missing, **dash_kw)
            print(
                f"[cli] incomplete matrix: {len(runs)}/{expected} cells, "
                f"{len(failed)} failed. No KEEP/REMOVE leaderboard."
            )
            if not profiles:
                print("[cli] every model was dropped (provider policy skip). Pass --models without the refusing provider.")
            elif policy_failed and args.strict_matrix:
                print("[cli] hint: omit the refusing model, e.g. --models opus,sonnet,haiku")
            print(f"[cli] wrote {dash}")
            raise SystemExit(2)

    if args.no_judge:
        return

    cases_by_id = {c.id: c for c in cases}
    judgments = judge_all(runs, cases_by_id, judge_provider, args.judge_model)
    judged_path = out_dir / f"judged_{ts}.json"
    judged_path.write_text(json.dumps(judgments_to_dicts(judgments), indent=2))
    print(f"[cli] wrote {judged_path}")

    failed_judgments = [j for j in judgments if j.score <= 0]
    missing_judge = unusable_judge_cells(judgments, cases, profiles)
    if missing_judge:
        dash = write_dashboard(None, status="incomplete", missing=missing_judge, **dash_kw)
        print(
            f"[cli] incomplete matrix: {len(judgments) - len(failed_judgments)}/{expected} "
            f"judged cells, {len(failed_judgments)} failed. No KEEP/REMOVE leaderboard."
        )
        print(f"[cli] wrote {dash}")
        raise SystemExit(2)

    deltas = analyze_deltas(judgments, profiles)
    elo = elo_ratings(judgments) if elo_ratings else None
    delta_ci = bootstrap_delta_ci(judgments, profiles) if bootstrap_delta_ci else None
    board = to_markdown(judgments, deltas, elo=elo, delta_ci=delta_ci or None)
    board_path = out_dir / f"leaderboard_{ts}.md"
    board_path.write_text(board + "\n")
    status = "partial" if dropped else ("complete" if deltas else "unpaired")
    dash = write_dashboard(
        board_path,
        deltas=deltas,
        status=status,
        missing=[f"dropped model {m}" for m in dropped] or None,
        **dash_kw,
    )
    print(f"[cli] wrote {board_path}\n\n{board}")
    print(f"[cli] wrote {dash}")


if __name__ == "__main__":
    main()
