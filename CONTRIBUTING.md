# Contributing to keep-or-cut

Thanks for helping make keep-or-cut useful beyond one model, tool, or local setup.

## Keep public inputs sterile

Cases, examples, fixtures, logs, screenshots, and documentation must not contain real usernames, email addresses, home-directory names, account IDs, API keys, private hostnames, subscription details, or names from unrelated projects. Use neutral placeholders such as `example-skill`, `user@example.com`, and `/tmp/keep-or-cut`.

Before committing, inspect both the diff and generated artifacts. Results belong in the ignored `results/` directory unless a maintainer explicitly requests a synthetic fixture.

## Set up and test

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install pytest
python -m pytest -q
```

An optional live smoke run uses whichever provider CLI is already configured on your machine:

```bash
python -m keep_or_cut.cli --smoke
```

## Preserve benchmark validity

Changes to scoring, profiles, or providers must preserve these invariants:

- Compare bare and treatment arms on the same cases.
- Fail closed when a Case × Profile cell is missing.
- Keep provider and model identity exact in commands and output.
- Isolate the bare arm from ambient skills, hooks, and memory.
- Inject each treatment once.

Add or update a focused test whenever one of these paths changes.

## Add a case

Place one YAML file in `cases/` using the existing `category`, `prompt`, and `rubric` fields. Keep the task model-agnostic, the rubric observable, and the expected behavior independent of private files or network access.

## Pull requests

Keep each pull request focused. Explain the user-visible change, call out any benchmark-validity impact, list the verification performed, and confirm that the diff contains no personal or secret material.
