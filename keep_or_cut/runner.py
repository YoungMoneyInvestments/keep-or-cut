from __future__ import annotations

import os
import time
from dataclasses import asdict

from keep_or_cut.context import build_system_prompt, wrap_request
from keep_or_cut.models import Case, Profile, Run
from keep_or_cut.providers import CALLERS, PolicySkipError, call_cli_harness, call_cli_skill_harness

POLICY_SKIP_PREFIX = "POLICY_SKIP:"


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


def _format_eta(seconds: float) -> str:
    if seconds < 1:
        return "0s"
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def run_all(
    cases: list[Case],
    profiles: list[Profile],
    wrap: str = "fair",
    *,
    disable_slash_baseline: bool | None = None,
    existing: list[Run] | None = None,
) -> list[Run]:
    """Sequential on purpose — a benchmark isn't a load test, and sequential runs are easy to
    read logs for. Parallelize later if the case/profile matrix gets big enough to matter."""
    if disable_slash_baseline is None:
        disable_slash_baseline = any(p.skill_name for p in profiles)
    prior = {
        (r.case_id, r.profile_id): r
        for r in (existing or [])
        if r.ok
    }
    total = len(cases) * len(profiles)
    done = 0
    started = time.monotonic()
    runs = []
    for case in cases:
        for profile in profiles:
            done += 1
            elapsed = time.monotonic() - started
            remaining = total - done
            eta = (elapsed / done) * remaining if done else 0
            prefix = f"[run] {done}/{total}"
            cached = prior.get((case.id, profile.id))
            if cached is not None:
                print(f"{prefix} resume {case.id} x {profile.id}")
                runs.append(cached)
                continue
            print(f"{prefix} {case.id} x {profile.id}  elapsed {_format_eta(elapsed)}  eta {_format_eta(eta)}")
            try:
                runs.append(
                    run_one(
                        case,
                        profile,
                        wrap=wrap,
                        disable_slash_baseline=disable_slash_baseline,
                    )
                )
            except PolicySkipError as e:
                print(f"[run] SKIP {case.id} x {profile.id}: {e}")
                runs.append(
                    Run(
                        case_id=case.id,
                        profile_id=profile.id,
                        output="",
                        latency_s=0.0,
                        input_tokens=0,
                        output_tokens=0,
                        error=f"{POLICY_SKIP_PREFIX} {e}",
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


def runs_from_dicts(rows: list[dict]) -> list[Run]:
    fields = set(Run.__dataclass_fields__)
    return [Run(**{k: v for k, v in row.items() if k in fields}) for row in rows]


def is_policy_skip(error: str) -> bool:
    return error.startswith(POLICY_SKIP_PREFIX) or "refusing a counting/enumeration" in error.lower()
