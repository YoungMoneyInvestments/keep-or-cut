"""CLI list/dry-run/resume/policy-skip/missing-dir behavior."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keep_or_cut.cli import main
from keep_or_cut.models import Case, Profile, Run
from keep_or_cut.runner import run_all, runs_from_dicts, runs_to_dicts


def _write_bench(tmp_path: Path, n_cases: int = 1) -> tuple[Path, Path, Path]:
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
    bundle = tmp_path / "notes-bundle"
    bundle.mkdir()
    (bundle / "notes.md").write_text("# example notes\n")
    out_dir = tmp_path / "results"
    return cases_dir, bundle, out_dir


def _argv(cases_dir: Path, bundle: Path, out_dir: Path, extra: list[str] | None = None) -> list[str]:
    args = [
        "keep-or-cut",
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
    if extra:
        args.extend(extra)
    return args


def _run(case_id: str, profile_id: str, error: str = "") -> Run:
    return Run(case_id, profile_id, "model output", 0.1, 10, 10, error=error)


def test_missing_context_dir_exits_before_runs(tmp_path, monkeypatch, capsys):
    cases_dir, _bundle, out_dir = _write_bench(tmp_path)
    missing = tmp_path / "nope"
    monkeypatch.setattr(
        sys,
        "argv",
        _argv(cases_dir, missing, out_dir),
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    err = capsys.readouterr()
    text = err.err + err.out
    assert "context dir not found" in text.lower()
    assert "nope" in text
    assert not (out_dir / "dashboard.html").exists()


def test_missing_cases_dir_names_the_path(tmp_path, monkeypatch, capsys):
    _cases_dir, bundle, out_dir = _write_bench(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        _argv(tmp_path / "missing-cases", bundle, out_dir),
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    blob = captured.out + captured.err
    assert "no cases" in blob.lower()
    assert "missing-cases" in blob


def test_list_prints_classes_and_skips_provider_calls(tmp_path, monkeypatch, capsys):
    cases_dir, bundle, out_dir = _write_bench(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    (home / "CLAUDE.md").write_text("# rules\n")
    skill = home / "skills" / "example-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# example-skill\n")
    (home / "hooks").mkdir()
    (home / "hooks" / "guard.py").write_text("print(1)\n")

    called = {"run": 0}

    def boom(*_a, **_k):
        called["run"] += 1
        raise AssertionError("list must not run models")

    monkeypatch.setattr("keep_or_cut.cli.run_all", boom)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "keep-or-cut",
            "--cases-dir",
            str(cases_dir),
            "--out-dir",
            str(out_dir),
            "--context-dir",
            str(home),
            "--models",
            "haiku",
            "--list",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert called["run"] == 0
    out = capsys.readouterr().out
    assert "claude.md" in out
    assert "skills" in out
    assert "cells:" in out.lower() or "cell" in out.lower()


def test_dry_run_prints_profiles_without_calling(tmp_path, monkeypatch, capsys):
    cases_dir, bundle, out_dir = _write_bench(tmp_path)
    monkeypatch.setattr(
        "keep_or_cut.cli.run_all",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("dry-run must not run")),
    )
    monkeypatch.setattr(sys, "argv", _argv(cases_dir, bundle, out_dir, ["--dry-run"]))
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "haiku" in out.lower() or "claude-haiku" in out
    assert "bare" in out


def test_policy_skip_drops_that_model_and_still_prints_keep(tmp_path, monkeypatch, capsys):
    cases_dir, bundle, out_dir = _write_bench(tmp_path, n_cases=1)

    def fake_run_all(cases, profiles, wrap="fair", **_kwargs):
        runs = []
        for case in cases:
            for profile in profiles:
                if profile.provider == "gemini" or "gemini" in profile.model:
                    runs.append(
                        _run(
                            case.id,
                            profile.id,
                            error="POLICY_SKIP: gmi: refusing a counting/enumeration question",
                        )
                    )
                else:
                    runs.append(_run(case.id, profile.id))
        return runs

    replies = iter(
        [
            ('{"score": 5, "reasoning": "bare"}', 1, 1),
            ('{"score": 8, "reasoning": "skill"}', 1, 1),
        ]
    )
    monkeypatch.setattr("keep_or_cut.cli.run_all", fake_run_all)
    monkeypatch.setattr(
        "keep_or_cut.judge.CALLERS",
        {"cli": lambda model, system, prompt: next(replies)},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        _argv(cases_dir, bundle, out_dir, ["--models", "haiku,gemini"]),
    )
    main()
    out = capsys.readouterr().out
    assert "KEEP" in out
    assert "dropped" in out.lower()
    assert "No KEEP/REMOVE leaderboard" not in out
    dash = (out_dir / "dashboard.html").read_text()
    assert "KEEP" in dash
    assert list(out_dir.glob("leaderboard_*.md"))


def test_strict_matrix_fail_closes_on_policy_skip(tmp_path, monkeypatch, capsys):
    cases_dir, bundle, out_dir = _write_bench(tmp_path, n_cases=1)

    def fake_run_all(cases, profiles, wrap="fair", **_kwargs):
        return [
            _run(case.id, profile.id, error="POLICY_SKIP: gmi refused")
            if (profile.provider == "gemini" or "gemini" in profile.model)
            else _run(case.id, profile.id)
            for case in cases
            for profile in profiles
        ]

    monkeypatch.setattr("keep_or_cut.cli.run_all", fake_run_all)
    monkeypatch.setattr(
        sys,
        "argv",
        _argv(cases_dir, bundle, out_dir, ["--models", "haiku,gemini", "--strict-matrix"]),
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "No KEEP/REMOVE leaderboard" in out


def test_resume_skips_completed_cells(monkeypatch):
    case = Case("case-1", "coding", "do it", ["did it"])
    profiles = [
        Profile("m+bare", "cli", "m", None),
        Profile("m+notes", "cli", "m", "/tmp/example"),
    ]
    existing = [_run("case-1", "m+bare")]
    calls = {"n": 0}

    def fake_one(case, profile, wrap="fair", **_k):
        calls["n"] += 1
        return _run(case.id, profile.id)

    monkeypatch.setattr("keep_or_cut.runner.run_one", fake_one)
    runs = run_all([case], profiles, existing=existing)
    assert calls["n"] == 1
    assert len(runs) == 2
    assert runs[0].profile_id == "m+bare"
    assert runs[1].profile_id == "m+notes"


def test_runs_from_dicts_roundtrip():
    original = [_run("case-1", "m+bare")]
    restored = runs_from_dicts(runs_to_dicts(original))
    assert restored[0].case_id == "case-1"
    assert restored[0].profile_id == "m+bare"
    assert restored[0].ok
