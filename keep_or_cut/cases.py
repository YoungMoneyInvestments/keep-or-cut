from __future__ import annotations

from pathlib import Path

import yaml

from keep_or_cut.models import Case


def load_cases(cases_dir: str = "cases") -> list[Case]:
    root = Path(cases_dir)
    cases = []
    for f in sorted(root.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text())
        except yaml.YAMLError as e:
            raise ValueError(f"invalid case file {f.name}: {e}") from e
        if not isinstance(data, dict):
            raise ValueError(f"invalid case file {f.name}: expected a mapping with category, prompt, rubric")
        missing = [key for key in ("category", "prompt", "rubric") if key not in data]
        if missing:
            raise ValueError(f"invalid case file {f.name}: missing {', '.join(missing)}")
        cases.append(Case(id=f.stem, category=data["category"], prompt=data["prompt"], rubric=data["rubric"]))
    return cases
