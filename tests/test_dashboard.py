"""Class × model dashboard: hero is categories vs models, not Helps/Elo."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keep_or_cut.dashboard import build_matrix, render_html, short_model, write_dashboard
from keep_or_cut.models import AblationDelta, Profile


def _delta(model, name, delta, rec, kind, n=2):
    return AblationDelta(
        model=model,
        skill_name=name,
        bare_score=7.0,
        with_skill_score=round(7.0 + delta, 2),
        delta=delta,
        recommendation=rec,
        kind=kind,
        n_paired=n,
    )


def test_short_model_strips_provider_ids():
    assert short_model("claude-haiku-4-5-20251001") == "Haiku"
    assert short_model("claude-sonnet-5") == "Sonnet"
    assert short_model("claude-opus-5") == "Opus"
    assert short_model("gpt-5.6-luna") == "Codex"
    assert short_model("xai:grok-4") == "Grok"


def test_matrix_is_class_rows_by_model_columns():
    deltas = [
        _delta("claude-haiku-4-5-20251001", "hooks", 0.5, "PROMPT_BLOAT", "hooks"),
        _delta("claude-sonnet-5", "hooks", -0.4, "PROMPT_BLOAT", "hooks"),
        _delta("claude-opus-5", "hooks", -1.5, "REMOVE", "hooks"),
        _delta("claude-opus-5", "skills", 1.6, "KEEP", "skills"),
        _delta("claude-haiku-4-5-20251001", "skills", 1.8, "KEEP", "skills"),
        _delta("claude-haiku-4-5-20251001", ".claude+all", 0.1, "PROMPT_BLOAT", ""),
    ]
    models, roots = build_matrix(deltas)
    labels = [short_model(m) for m in models]
    assert labels == ["Haiku", "Sonnet", "Opus"]
    ids = [r.id for r in roots]
    assert ids == ["skills", "hooks"]
    assert "+all" not in ids
    hooks = next(r for r in roots if r.id == "hooks")
    assert hooks.cells["claude-opus-5"].recommendation == "REMOVE"
    assert hooks.cells["claude-opus-5"].delta == -1.5
    assert hooks.cells["claude-sonnet-5"].delta is not None


def test_html_paints_calls_and_hides_elo():
    deltas = [
        _delta("claude-haiku-4-5-20251001", "claude.md", 2.0, "KEEP", "claude.md"),
        _delta("claude-opus-5", "claude.md", -1.2, "REMOVE", "claude.md"),
        _delta("claude-haiku-4-5-20251001", "hooks", -1.4, "REMOVE", "hooks"),
        _delta("gpt-5.6-luna", "hooks", 0.1, "PROMPT_BLOAT", "hooks"),
        _delta("grok-4", "hooks", 1.6, "KEEP", "hooks"),
    ]
    page = render_html(
        "# leftover\n\n## Arena-style Elo\n\n| Profile | Elo |\n|---|---|\n| `x` | 1200 |\n",
        deltas=deltas,
        home="~/.claude",
        n_cases=10,
        status="complete",
    )
    assert "CLAUDE.md" in page
    assert "Haiku" in page and "Opus" in page and "Codex" in page and "Grok" in page
    assert "claude-haiku-4-5-20251001" not in page
    assert "class=\"cell keep\"" in page
    assert "class=\"cell remove\"" in page
    assert "class=\"cell bloat\"" in page
    assert "+2.00" in page
    assert "KEEP" in page and "REMOVE" in page and "PROMPT_BLOAT" in page
    assert "Arena-style" not in page
    assert "Helps" not in page
    assert "1200" not in page


def test_skills_nest_under_category():
    deltas = [
        _delta("claude-opus-5", "skills/linting-audit", -1.4, "REMOVE", "skills"),
        _delta("claude-opus-5", "skills/linting-debug", -0.8, "PROMPT_BLOAT", "skills"),
        _delta("claude-opus-5", "skills/example-skill", 0.2, "PROMPT_BLOAT", "skills"),
        _delta("claude-haiku-4-5-20251001", "skills/linting-audit", 0.5, "PROMPT_BLOAT", "skills"),
    ]
    models, roots = build_matrix(deltas)
    assert [r.id for r in roots] == ["skills"]
    child_ids = [c.id for c in roots[0].children]
    assert "skills/linting" in child_ids
    assert "skills/example-skill" in child_ids
    lint = next(c for c in roots[0].children if c.id == "skills/linting")
    assert {k.id for k in lint.children} == {"skills/linting-audit", "skills/linting-debug"}
    page = render_html(deltas=deltas)
    assert 'data-toggle="skills"' in page
    assert 'data-parent="skills/linting"' in page
    assert "linting-audit" in page
    assert "skills (" in page


def test_family_only_matrix_still_gets_a_skills_root():
    """--split skills with every leaf sharing a prefix and no lone singleton skill.

    Regression: parent synthesis used to run in a single pass, so a family row
    (e.g. "skills/linting") got created but its own missing parent ("skills")
    never did — every row ended up with a non-empty `.parent` that pointed at
    nothing in `by_id`, so `roots` (rows with no parent) came back empty and
    the dashboard rendered zero rows.
    """
    deltas = [
        _delta("claude-opus-5", "skills/linting-audit", -1.4, "REMOVE", "skills"),
        _delta("claude-opus-5", "skills/linting-debug", -0.8, "PROMPT_BLOAT", "skills"),
    ]
    models, roots = build_matrix(deltas)
    assert [r.id for r in roots] == ["skills"]
    assert [c.id for c in roots[0].children] == ["skills/linting"]
    lint = roots[0].children[0]
    assert {k.id for k in lint.children} == {"skills/linting-audit", "skills/linting-debug"}


def test_n_zero_cell_has_no_call():
    deltas = [
        AblationDelta("claude-opus-5", "hooks", 0.0, 0.0, 0.0, "KEEP", kind="hooks", n_paired=0),
        _delta("claude-opus-5", "agents", 0.6, "PROMPT_BLOAT", "agents"),
    ]
    _models, roots = build_matrix(deltas)
    hooks = next(r for r in roots if r.id == "hooks")
    assert hooks.cells["claude-opus-5"].delta is None
    page = render_html(deltas=deltas)
    assert "— N=0" in page
    assert 'class="cell keep"' not in page


def test_incomplete_writes_banner_not_calls(tmp_path):
    profiles = [
        Profile("haiku+bare", "cli", "claude-haiku-4-5-20251001", None),
        Profile("haiku+hooks", "cli", "claude-haiku-4-5-20251001", "/tmp/x", class_id="hooks", kind="hooks"),
    ]
    out = write_dashboard(
        None,
        tmp_path / "dashboard.html",
        profiles=profiles,
        status="incomplete",
        missing=["01_resource_guide × haiku+hooks"],
        home="~/.claude",
        n_cases=1,
    )
    text = out.read_text()
    assert "Matrix incomplete" in text
    assert "01_resource_guide" in text
    assert "KEEP Δ≥+1.5" in text
    assert 'class="cell keep"' not in text
    assert "hooks" in text


def test_md_fallback_hides_profiles_and_elo(tmp_path):
    md = tmp_path / "leaderboard.md"
    md.write_text(
        "# Context-Bench Leaderboard\n\n"
        "## Profiles\n\n| Profile | Mean Score |\n|---|---|\n| `demo-haiku+example` | 9.0 |\n\n"
        "## Arena-style Elo\n\n| Profile | Elo |\n|---|---|\n| `x` | 1400 |\n\n"
        "## Same model, with vs without the extra context\n\n"
        "| Model | What it did |\n|---|---|\n| `demo-haiku` | **Helps** |\n"
    )
    page = write_dashboard(md, tmp_path / "out.html").read_text()
    assert ">Helps<" not in page
    assert "1400" not in page
    assert "demo-haiku+example" not in page


if __name__ == "__main__":
    test_short_model_strips_provider_ids()
    test_matrix_is_class_rows_by_model_columns()
    test_html_paints_calls_and_hides_elo()
    test_skills_nest_under_category()
    test_family_only_matrix_still_gets_a_skills_root()
    test_n_zero_cell_has_no_call()
    print("ok")
