"""Provider CLI callers."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keep_or_cut.providers import (
    call_cli_harness,
    call_cli_skill_harness,
    call_cursor_cli,
    call_gemini_cli,
)


def test_call_cursor_cli_invokes_subprocess_with_ask_mode():
    mock_result = MagicMock()
    mock_result.stdout = "  bench answer  "
    with patch("keep_or_cut.providers.subprocess.run", return_value=mock_result) as mock_run:
        text, in_tok, out_tok = call_cursor_cli("auto", "context notes", "do the task")

    assert text == "bench answer"
    assert in_tok > 0
    assert out_tok > 0

    mock_run.assert_called_once()
    cmd, kwargs = mock_run.call_args[0][0], mock_run.call_args[1]
    assert cmd[0] == "cursor-agent"
    assert "-p" in cmd
    assert "--mode" in cmd and cmd[cmd.index("--mode") + 1] == "ask"
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "text"
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "auto"
    assert "--workspace" in cmd
    assert cmd[-1] == "context notes\n\ndo the task"
    assert kwargs["timeout"] == 180
    assert kwargs["check"] is True
    assert kwargs["cwd"] == cmd[cmd.index("--workspace") + 1]


def test_call_cursor_cli_no_system_uses_prompt_only():
    mock_result = MagicMock()
    mock_result.stdout = "ok"
    with patch("keep_or_cut.providers.subprocess.run", return_value=mock_result) as mock_run:
        call_cursor_cli("auto", "", "just the task")

    cmd = mock_run.call_args[0][0]
    assert cmd[-1] == "just the task"


def test_call_cursor_cli_raises_runtime_error_on_failure():
    with patch(
        "keep_or_cut.providers.subprocess.run",
        side_effect=RuntimeError("boom"),
    ):
        try:
            call_cursor_cli("auto", "", "fail")
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "cursor CLI execution failed" in str(exc)


def test_call_cli_skill_harness_uses_slash_invoke_not_system_file():
    mock_result = MagicMock()
    mock_result.stdout = "  pong  "
    with patch("keep_or_cut.providers.subprocess.run", return_value=mock_result) as mock_run:
        text, in_tok, out_tok = call_cli_skill_harness(
            "claude-haiku-4-5-20251001",
            "ignore these notes",
            "Task: pong",
            skill_name="example-skill",
        )

    assert text == "pong"
    assert in_tok > 0
    assert out_tok > 0

    mock_run.assert_called_once()
    cmd, kwargs = mock_run.call_args[0][0], mock_run.call_args[1]
    assert cmd[0] == "claude"
    assert cmd[1] == "-p"
    assert "/example-skill" in cmd[2]
    assert "Task: pong" in cmd[2]
    assert "--system-prompt-file" not in cmd
    assert "--system-prompt" not in cmd
    assert "ignore these notes" in cmd[2]
    assert kwargs["timeout"] == 180
    assert kwargs["check"] is True


def test_call_cli_harness_disable_slash_flag():
    mock_result = MagicMock()
    mock_result.stdout = "ok"
    with patch("keep_or_cut.providers.subprocess.run", return_value=mock_result) as mock_run:
        call_cli_harness("claude-opus-5", "", "task only", disable_slash=True)

    cmd = mock_run.call_args[0][0]
    assert "--safe-mode" in cmd
    assert "--disable-slash-commands" in cmd


def test_call_gemini_cli_prefers_gmi_when_available():
    mock_result = MagicMock()
    mock_result.stdout = "  gemini answer  "
    with (
        patch("shutil.which", return_value="/usr/local/bin/gmi"),
        patch("keep_or_cut.providers.subprocess.run", return_value=mock_result) as mock_run,
    ):
        text, in_tok, out_tok = call_gemini_cli(
            "gemini-3.6-flash-high", "context notes", "do the task"
        )

    assert text == "gemini answer"
    assert in_tok > 0
    assert out_tok > 0
    cmd, kwargs = mock_run.call_args[0][0], mock_run.call_args[1]
    assert cmd == ["gmi", "--model", "gemini-3.6-flash-high", "context notes\n\ndo the task"]
    assert kwargs["timeout"] == 180


def test_call_gemini_cli_falls_back_to_gemini_binary():
    mock_result = MagicMock()
    mock_result.stdout = "  gemini answer  "
    with (
        patch("shutil.which", return_value=None),
        patch("keep_or_cut.providers.subprocess.run", return_value=mock_result) as mock_run,
    ):
        call_gemini_cli("gemini-2.5-flash", "context notes", "do the task")

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "gemini"
    assert "-p" in cmd
    assert "--approval-mode" in cmd and cmd[cmd.index("--approval-mode") + 1] == "plan"
    assert "-y" not in cmd


def test_call_gemini_cli_timeout_raises_login_hint():
    import subprocess

    with (
        patch("shutil.which", return_value=None),
        patch(
            "keep_or_cut.providers.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["gemini"], timeout=180),
        ),
    ):
        try:
            call_gemini_cli("gemini-2.5-flash", "", "task")
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "gemini" in str(exc).lower()
