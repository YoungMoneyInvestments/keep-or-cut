# `bare` is relative to Ambient Config, not absolute zero, under OAuth

Verified by live probe (2026-08-14): `claude -p` unconditionally loads the operator's
`~/.claude/CLAUDE.md` on every call when authenticated via OAuth/keychain — asking it a private
CLAUDE.md-only question through a fresh empty working directory with `--disable-slash-commands
--strict-mcp-config --settings <empty>` still returned the private answer verbatim. The one flag
that does disable CLAUDE.md/skill/hook auto-discovery, `--bare` (equivalently
`CLAUDE_CODE_SIMPLE=1`), documents itself as forcing `ANTHROPIC_API_KEY`/`apiKeyHelper` auth only
— "OAuth and keychain are never read." Confirmed by direct probe: `--bare` and `CLAUDE_CODE_SIMPLE=1`
both fail with "Not logged in" under a keychain-only OAuth session. There is no flag combination
that yields zero Ambient Config while keeping OAuth.

Given [the OAuth-only requirement](./0002-omniroute-oauth-subscription-routing.md), true
clean-room `bare` is not achievable for the CLI-harness Provider. Rather than block on it, `bare`
is redefined as "no added Context Bundle," not "no context at all" — Ambient Config (the
operator's own CLAUDE.md/skills/hooks) loads identically across every Profile in a run, so it's a
constant that cancels out of the `bare` vs. `+context` Delta, which is what the Leaderboard's
recommendations are actually built on. What does NOT survive this: absolute scores are not
comparable across two different operators' machines, only Deltas within one operator's own run
are. This also reframes the tool for the better — it's not a universal cross-user leaderboard, it's
a personalized ablation check ("does adding *this* context bundle help or hurt, given what I
already run"), which is closer to Boris Cherny's actual advice ("delete *your* skills") than a
synthetic absolute score ever was. Considered forcing `ANTHROPIC_API_KEY` for the `bare` arm only
to get a real clean-room baseline — rejected because we explicitly ruled out API keys, and a
mixed-auth benchmark (OAuth for one arm, API key for the other) would confound model behavior
differences with auth-path differences, which is worse than the constant-Ambient-Config tradeoff.
