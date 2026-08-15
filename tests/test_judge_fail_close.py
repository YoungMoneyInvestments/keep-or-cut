"""Fail-closed judge cells: score 0 or a provider exception must not emit KEEP."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keep_or_cut.cli import main, unusable_judge_cells
from keep_or_cut.judge import judge_all
from keep_or_cut.models import Case, Judgment, Profile, Run


def _case(case_id: str) -> Case:
    return Case(case_id, "coding", "do the thing", ["did the thing"])


def _run(case_id: str, profile_id: str) -> Run:
    return Run(case_id, profile_id, "model output", 0.1, 10, 10)


def _write_bench(tmp_path: Path, n_cases: int = 2) -> tuple[Path, Path, Path]:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    for i in range(n_cases):
        (cases_dir / f"case-{i + 1}.yaml").write_text(
            "category: coding\n"
            "prompt: |\n"
            "  do the thing\n"
            "rubric:\n"
            "  - did the thing\n"
        )
    bundle = tmp_path / "example-skill"
    bundle.mkdir()
    (bundle / "notes.md").write_text("# example notes\n")
    out_dir = tmp_path / "results"
    return cases_dir, bundle, out_dir


def _argv(cases_dir: Path, bundle: Path, out_dir: Path) -> list[str]:
    return [
        "keep_or_cut",
        "--cases-dir",
        str(cases_dir),
        "--out-dir",
        str(out_dir),
        "--context-dir",
        str(bundle),
        "--split",
        "off",
        "--models",
        "haiku",
        "--harness",
        "notes",
    ]


def _successful_runs(cases, profiles):
    return [_run(case.id, profile.id) for case in cases for profile in profiles]


def test_judge_all_records_provider_exception_and_continues(monkeypatch):
    calls = {"n": 0}

    def caller(model, system, prompt):
        calls["n"] += 1
        if calls["n"] == 2:
            raise TimeoutError("judge timed out")
        return '{"score": 7, "reasoning": "ok"}', 1, 1

    monkeypatch.setattr("keep_or_cut.judge.CALLERS", {"cli": caller})
    runs = [_run("case-1", "m+bare"), _run("case-1", "m+skill"), _run("case-2", "m+bare")]
    cases = {"case-1": _case("case-1"), "case-2": _case("case-2")}
    judgments = judge_all(runs, cases, "cli", "claude-opus-5")
    assert [j.score for j in judgments] == [7, 0, 7]
    assert "TimeoutError" in judgments[1].reasoning
    assert judgments[1].case_id == "case-1"
    assert judgments[1].profile_id == "m+skill"
    assert calls["n"] == 3


def test_unusable_judge_cells_lists_score_zero_and_missing():
    profiles = [
        Profile("m+bare", "cli", "m", None),
        Profile("m+skill", "cli", "m", "/tmp/example-skill"),
    ]
    cases = [_case("case-a"), _case("case-b")]
    judgments = [
        Judgment("case-a", "m+bare", 6, "ok", "j"),
        Judgment("case-a", "m+skill", 8, "ok", "j"),
        Judgment("case-b", "m+bare", 0, "unparseable judge output: 'nope'", "j"),
    ]
    missing = unusable_judge_cells(judgments, cases, profiles)
    assert any("case-b × m+skill" == cell for cell in missing)
    assert any("case-b × m+bare" in cell and "unparseable" in cell for cell in missing)
    assert not any(cell.startswith("case-a ×") for cell in missing)


def test_cli_fail_closes_on_unparseable_score(tmp_path, monkeypatch, capsys):
    """One garbage verdict must not let the other paired case print KEEP."""
    cases_dir, bundle, out_dir = _write_bench(tmp_path)
    monkeypatch.setattr("keep_or_cut.cli.run_all", _successful_runs)

    replies = iter(
        [
            ('{"score": 5, "reasoning": "bare a"}', 1, 1),
            ('{"score": 8, "reasoning": "skill a"}', 1, 1),
            ('{"score": 5, "reasoning": "bare b"}', 1, 1),
            ("not json at all", 1, 1),
        ]
    )
    monkeypatch.setattr(
        "keep_or_cut.judge.CALLERS",
        {"cli": lambda model, system, prompt: next(replies)},
    )
    monkeypatch.setattr(sys, "argv", _argv(cases_dir, bundle, out_dir))

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2

    out = capsys.readouterr().out
    assert "No KEEP/REMOVE leaderboard" in out
    assert "Skill Ablation" not in out
    dash = (out_dir / "dashboard.html").read_text()
    assert "Matrix incomplete" in dash
    assert 'class="cell keep"' not in dash
    assert not list(out_dir.glob("leaderboard_*.md"))
    judged = json.loads(next(out_dir.glob("judged_*.json")).read_text())
    assert any(row["score"] == 0 for row in judged)


def test_cli_fail_closes_on_judge_exception(tmp_path, monkeypatch, capsys):
    cases_dir, bundle, out_dir = _write_bench(tmp_path)
    monkeypatch.setattr("keep_or_cut.cli.run_all", _successful_runs)

    calls = {"n": 0}

    def caller(model, system, prompt):
        calls["n"] += 1
        if calls["n"] == 4:
            raise KeyError("missing judge provider")
        score = 8 if calls["n"] == 2 else 5
        return f'{{"score": {score}, "reasoning": "ok"}}', 1, 1

    monkeypatch.setattr("keep_or_cut.judge.CALLERS", {"cli": caller})
    monkeypatch.setattr(sys, "argv", _argv(cases_dir, bundle, out_dir))

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert calls["n"] == 4

    out = capsys.readouterr().out
    assert "No KEEP/REMOVE leaderboard" in out
    assert "FAILED" in out
    dash = (out_dir / "dashboard.html").read_text()
    assert "Matrix incomplete" in dash
    assert "KeyError" in dash
    assert 'class="cell keep"' not in dash
    assert not list(out_dir.glob("leaderboard_*.md"))


def test_cli_prints_keep_when_every_judge_cell_is_usable(tmp_path, monkeypatch, capsys):
    cases_dir, bundle, out_dir = _write_bench(tmp_path, n_cases=1)
    monkeypatch.setattr("keep_or_cut.cli.run_all", _successful_runs)
    replies = iter(
        [
            ('{"score": 5, "reasoning": "bare"}', 1, 1),
            ('{"score": 8, "reasoning": "skill"}', 1, 1),
        ]
    )
    monkeypatch.setattr(
        "keep_or_cut.judge.CALLERS",
        {"cli": lambda model, system, prompt: next(replies)},
    )
    monkeypatch.setattr(sys, "argv", _argv(cases_dir, bundle, out_dir))

    main()
    out = capsys.readouterr().out
    assert "KEEP" in out
    assert "No KEEP/REMOVE leaderboard" not in out
    dash = (out_dir / "dashboard.html").read_text()
    assert "Matrix incomplete" not in dash
    assert list(out_dir.glob("leaderboard_*.md"))
