from __future__ import annotations

from collections import defaultdict

from keep_or_cut.models import AblationDelta, Judgment

# Stronger model → higher rank. Used only to say "fading" when delta drops.
_MODEL_TIER = {
    "claude-haiku-4-5-20251001": 0,
    "claude-haiku-4.5": 0,
    "claude-sonnet-5": 1,
    "claude-opus-5": 2,
}


def _tier(model: str) -> int | None:
    if model in _MODEL_TIER:
        return _MODEL_TIER[model]
    for key, val in _MODEL_TIER.items():
        if key in model or model in key:
            return val
    return None


def _trend(class_deltas: list[AblationDelta]) -> str:
    """If stronger models get less lift from this class, it is fading."""
    ranked = [( _tier(d.model), d.delta) for d in class_deltas if _tier(d.model) is not None]
    ranked = [(t, d) for t, d in ranked if t is not None]
    if len(ranked) < 2:
        return "—"
    ranked.sort(key=lambda item: item[0])
    first, last = ranked[0][1], ranked[-1][1]
    if last <= -1.0 and first > last:
        return "fading — stronger models need it less"
    if last + 0.4 < first:
        return "fading"
    if last >= 1.5 and last >= first:
        return "still earning"
    return "—"


def class_matrix_markdown(deltas: list[AblationDelta]) -> str:
    """Models × classes. This is the table a pile-of-skills user came for."""
    class_ids = []
    models = []
    by: dict[tuple[str, str], AblationDelta] = {}
    for d in deltas:
        if not d.kind:
            continue
        by[(d.model, d.skill_name)] = d
        if d.skill_name not in class_ids:
            class_ids.append(d.skill_name)
        if d.model not in models:
            models.append(d.model)
    if not class_ids or not models:
        return ""

    def _sort_model(m: str) -> tuple[int, str]:
        t = _tier(m)
        return (t if t is not None else 50, m)

    models = sorted(models, key=_sort_model)
    header = "| Class | " + " | ".join(f"`{m}`" for m in models) + " | Worst Δ | Call | Trend |"
    sep = "|" + "---|" * (len(models) + 4)
    lines = [
        "## Which classes still earn tokens",
        "",
        "Each class is scored **alone** against bare. Read down a column: if Opus is worse "
        "than Haiku on the same class, that class is what newer models are outgrowing.",
        "",
        header,
        sep,
    ]
    # Rank classes by most-negative mean delta (biggest bloat first).
    def mean_delta(cid: str) -> float:
        vals = [by[(m, cid)].delta for m in models if (m, cid) in by]
        return sum(vals) / len(vals) if vals else 0.0

    for cid in sorted(class_ids, key=mean_delta):
        cells = []
        class_ds = []
        for m in models:
            d = by.get((m, cid))
            if not d:
                cells.append("—")
                continue
            class_ds.append(d)
            cells.append(f"{d.delta:+.2f}")
        worst = min(class_ds, key=lambda d: d.delta)
        lines.append(
            f"| `{cid}` | " + " | ".join(cells)
            + f" | {worst.delta:+.2f} | **{worst.recommendation}** | {_trend(class_ds)} |"
        )
    lines.extend([
        "",
        "Worst Δ is the most negative model on that class — that is the bloat signal. "
        "A class that is KEEP on Haiku and REMOVE on Opus is the one to delete first "
        "when you upgrade the model.",
    ])
    return "\n".join(lines)


def aggregate(judgments: list[Judgment]) -> list[tuple[str, float, int]]:
    """Returns (profile_id, mean_score, n_cases) sorted best-first. Excludes unparseable (score=0)
    judgments from the mean but still counts them toward n_cases via their own row context."""
    by_profile: dict[str, list[int]] = defaultdict(list)
    for j in judgments:
        if j.score > 0:
            by_profile[j.profile_id].append(j.score)
    rows = [(pid, sum(scores) / len(scores), len(scores)) for pid, scores in by_profile.items() if scores]
    return sorted(rows, key=lambda r: r[1], reverse=True)


def to_markdown(
    judgments: list[Judgment],
    deltas: list[AblationDelta] | None = None,
    elo: dict[str, float] | None = None,
    delta_ci: list[dict] | None = None,
) -> str:
    rows = aggregate(judgments)
    mean_by_profile = {pid: mean for pid, mean, _ in rows}
    lines = ["# Context-Bench Leaderboard", ""]
    if deltas:
        matrix = class_matrix_markdown(deltas)
        if matrix:
            lines.extend([matrix, ""])
    lines.extend([
        "## Profiles",
        "",
        "| Profile | Mean Score | Cases Judged |",
        "|---|---|---|",
    ])
    for pid, mean, n in rows:
        lines.append(f"| `{pid}` | {mean:.1f} | {n} |")

    if elo:
        elo_rows = sorted(elo.items(), key=lambda item: item[1], reverse=True)
        lines.extend([
            "",
            "## Arena-style Elo",
            "",
            "Pairwise wins from per-case score comparisons (Bradley-Terry / Elo). "
            "Absolute ratings are within-run only — compare profiles in this leaderboard, "
            "not across machines or runs.",
            "",
            "| Profile | Elo | Mean Score |",
            "|---|---|---|",
        ])
        for pid, rating in elo_rows:
            mean = mean_by_profile.get(pid)
            mean_cell = f"{mean:.1f}" if mean is not None else "—"
            lines.append(f"| `{pid}` | {rating:.0f} | {mean_cell} |")

    if deltas:
        ci_lookup = {
            (row["model"], row["skill_name"]): row
            for row in (delta_ci or [])
        }
        if delta_ci:
            header = (
                "| Model | Skill / Context | Bare Score | With Context | Delta (Δ) | "
                "CI Low | CI High | Recommendation |"
            )
            separator = "|---|---|---|---|---|---|---|---|"
        else:
            header = (
                "| Model | Skill / Context | Bare Score | With Context | Delta (Δ) | Recommendation |"
            )
            separator = "|---|---|---|---|---|---|"

        lines.extend([
            "",
            "## Skill Ablation & Recommendation Matrix",
            "",
            header,
            separator,
        ])
        for d in deltas:
            icon = "✅" if d.recommendation == "KEEP" else ("❌" if d.recommendation == "REMOVE" else "🧹")
            ci = ci_lookup.get((d.model, d.skill_name))
            if ci:
                lines.append(
                    f"| `{d.model}` | `{d.skill_name}` | {d.bare_score} | {d.with_skill_score} | "
                    f"{d.delta:+.2f} | {ci['ci_low']:+.2f} | {ci['ci_high']:+.2f} | "
                    f"{icon} **{d.recommendation}** |"
                )
            else:
                lines.append(
                    f"| `{d.model}` | `{d.skill_name}` | {d.bare_score} | {d.with_skill_score} | "
                    f"{d.delta:+.2f} | {icon} **{d.recommendation}** |"
                )
        lines.extend([
            "",
            "**What to do about it** (this is whole-bundle Delta, not per-file — it tells you"
            " *whether* to cut, not *which lines*):",
            "- ✅ **KEEP** (Δ ≥ +1.5): clear win here, leave it as-is.",
            "- 🧹 **PROMPT_BLOAT** (-1.0 < Δ < +1.5): not clearly earning its token cost on these"
            " case types. Split the bundle into smaller files and re-run — the ones with Δ near"
            " zero on their own are what to cut first.",
            "- ❌ **REMOVE** (Δ ≤ -1.0): actively made the model worse here. Don't just delete it —"
            " read a couple of `results/judged_*.json` reasoning strings for this profile first;"
            " a large negative Δ is sometimes a harness artifact (e.g. issue #1's raw"
            " system-prompt wrapping) rather than the content itself being bad.",
        ])

    return "\n".join(lines)
