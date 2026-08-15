# Fair CLI wrapping: task is the user message

## Context

Issue #1: dumping a real `SKILL.md` into `claude -p` as

```
System Instructions:
{skill.md}

Task:
{case prompt}
```

made Opus 5 / Sonnet 5 refuse the Case (injection suspicion, skill help-text, "no actual task"). Haiku still attempted the work. The resulting `REMOVE` verdicts were a wrapping artifact, not evidence the skill is harmful inside Claude Code.

## Decision

- Default wrap mode is `fair`: the Case is the user message. Bundle notes go through `claude --system-prompt-file` (or the API `system` role) behind a short preamble that says they are optional reference and must not block the task.
- `--wrap system` sends the notes as a raw system prompt (right for CLAUDE.md-shaped prose).
- `--wrap raw` reproduces the old user-turn stuffing so the bug is still measurable.
- `--context-dir PATH` (repeatable) is how you point the bench at your own bundle. ADR 0001 already described this flag; the CLI now actually has it.

## Consequences

Fair wrap stops the false "model refused" collapse when SKILL.md is dumped as a system prompt; it does not claim a skill works the same way it would under `/skill` or auto-invocation.

## Update (2026-08-14): skill harness shipped

Real Claude Code skill invocation is now supported via `--harness auto` (default) or `--harness skill`:

- Skill directories (`.../skills/<name>/SKILL.md`) set `Profile.skill_name` and the runner calls `call_cli_skill_harness`, which builds `/{skill_name}\n\n{case prompt}` for `claude -p`.
- SKILL.md is **not** passed via `--system-prompt-file` on skill profiles — that path still triggers Opus/Sonnet refusal (issue #1 mechanism).
- Bare baseline arms in the same run pass `--disable-slash-commands` so slash skills do not activate during comparison.
- **`--bare` is forbidden** on the Claude CLI harness: it drops OAuth and fails with "Not logged in". Do not use it.
- **`CLAUDE_CONFIG_DIR` isolation is forbidden** for the same reason — it loses OAuth.
- `--harness notes` preserves the old fair/system/raw wrap for A/B against the slash path.

See `keep_or_cut/providers.py:call_cli_skill_harness` and `keep_or_cut/runner.py`.

## Update (2026-08-15): Grok has a real system-role flag

`call_grok_cli` previously concatenated notes into `--single` on the claim that
`grok` had no system-role flag. Current Grok Build exposes `--system-prompt`
(alias of `--system-prompt-override`). Fair/system wrap now pass notes there so
the Case stays the user message on Grok the same way they do on `claude -p`.
