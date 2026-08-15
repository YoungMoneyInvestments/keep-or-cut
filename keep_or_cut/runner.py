from __future__ import annotations

import os
import time
from dataclasses import asdict

from keep_or_cut.context import build_system_prompt, wrap_request
from keep_or_cut.models import Case, Profile, Run
from keep_or_cut.providers import CALLERS, call_cli_harness, call_cli_skill_harness


def _uses_cli_skill_harness(profile: Profile) -> bool:
    if not profile.skill_name:
        return False
    if profile.provider == "cli":
        return True
    return profile.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY")


def _bare_cli_baseline(profile: Profile, disable_slash_baseline: bool) -> bool:
    return (
        disable_slash_baseline
        and profile.context_dir is None
        and (profile.provider == "cli" or (
            profile.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY")
        ))
    )


def run_one(
    case: Case,
    profile: Profile,
    wrap: str = "fair",
    *,
    disable_slash_baseline: bool = False,
) -> Run:
    start = time.monotonic()

    if _uses_cli_skill_harness(profile):
        text, in_tok, out_tok = call_cli_skill_harness(
            profile.model,
            system="",
            prompt=case.prompt,
            skill_name=profile.skill_name,
        )
    else:
        notes = build_system_prompt(
            profile.context_dir,
            include=profile.include,
            extra_notes=profile.extra_notes,
        )
        system, user = wrap_request(case.prompt, notes, wrap)
        if _bare_cli_baseline(profile, disable_slash_baseline):
            text, in_tok, out_tok = call_cli_harness(
                profile.model, system, user, disable_slash=True
            )
        else:
            caller = CALLERS[profile.provider]
            text, in_tok, out_tok = caller(profile.model, system, user)

    latency = time.monotonic() - start
    return Run(
        case_id=case.id,
        profile_id=profile.id,
        output=text,
        latency_s=round(latency, 2),
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def run_all(
    cases: list[Case],
    profiles: list[Profile],
    wrap: str = "fair",
    *,
    disable_slash_baseline: bool | None = None,
) -> list[Run]:
    """Sequential on purpose — a benchmark isn't a load test, and sequential runs are easy to
    read logs for. Parallelize later if the case/profile matrix gets big enough to matter."""
    if disable_slash_baseline is None:
        disable_slash_baseline = any(p.skill_name for p in profiles)
    runs = []
    for case in cases:
        for profile in profiles:
            print(f"[run] {case.id} x {profile.id}")
            try:
                runs.append(
                    run_one(
                        case,
                        profile,
                        wrap=wrap,
                        disable_slash_baseline=disable_slash_baseline,
                    )
                )
            except Exception as e:  # record the cell; CLI fail-closes the leaderboard
                print(f"[run] FAILED {case.id} x {profile.id}: {e}")
                runs.append(
                    Run(
                        case_id=case.id,
                        profile_id=profile.id,
                        output="",
                        latency_s=0.0,
                        input_tokens=0,
                        output_tokens=0,
                        error=f"{type(e).__name__}: {e}",
                    )
                )
    return runs


def runs_to_dicts(runs: list[Run]) -> list[dict]:
    return [asdict(r) for r in runs]
