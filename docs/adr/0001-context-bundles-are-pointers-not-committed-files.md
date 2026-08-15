# Context Bundles are pointers, not committed files

This is a public repo. A user's real "full context" (their CLAUDE.md, skills, business details)
is exactly the kind of thing that should never end up in a public git history — and it would also
make the benchmark useless to anyone else, since it'd be scored on one operator's setup, not theirs.
So `--context-dir` always points at a local, gitignored directory the user supplies at run time.
The repo ships one synthetic `examples/context/` bundle for demo purposes only, clearly labeled as
fictional. Considered shipping a "realistic" bundle instead — rejected because there's no such
thing as a realistic bundle that isn't someone's actual private config.
