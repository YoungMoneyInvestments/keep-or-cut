# ADR 0002: Subscription CLI / OAuth routing vs API keys

## Status
Accepted — **Superseded in practice by direct CLI harness (`claude` / `grok` / `codex` / `cursor-agent` / `gmi` OAuth adapters); OmniRoute optional/fallback only.**

## Context
1. **Goal**: Run model comparisons on existing **subscriptions / OAuth CLI sessions**, not pay-per-token API keys.
2. **Goal of the Benchmark**: Measure how a user's *local environment* (active `CLAUDE.md`, skills, hooks, MCP tools) changes output quality vs a bare baseline.
3. **The Architectural Conflict**:
   - Direct provider API calls (`anthropic.Anthropic()`, `openai.OpenAI()`) require paid API keys (`sk-...`) per token. They bypass local CLI hooks, system prompts, skills, and OAuth session tokens.
   - Calling raw LLM APIs with system prompts tests static prompt engineering, but does **not** exercise live CLI harness behaviors (tool calls, skill dispatch, hooks).
   - Local CLIs already hold authenticated subscription sessions; routing through them matches real usage without shipping keys into the repo.

## Decision
1. **Prefer per-provider CLI adapters** in `keep-or-cut` (`claude -p`, `grok`, `codex exec`, `cursor-agent`, `gmi`).
2. **OmniRoute remains optional** as an explicit `--provider omniroute` fallback, not the default path.
3. **Acknowledge the Layer Distinction**:
   - **Layer A (Prompt/Context Benchmarking)**: Extra markdown context via system/user wrapping on a CLI/API call.
   - **Layer B (Live Harness Benchmarking)**: Real skill slash-invoke (`claude -p /skillname`) and similar harness loops.

## Consequences
- No API keys need to live in the repo or CI secrets for the default path.
- Absolute scores stay operator-local under OAuth ambient config (see ADR 0003).
