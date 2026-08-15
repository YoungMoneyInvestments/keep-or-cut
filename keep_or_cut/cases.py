from __future__ import annotations

from pathlib import Path

import yaml

from keep_or_cut.models import Case


def load_cases(cases_dir: str = "cases") -> list[Case]:
    root = Path(cases_dir)
    cases = []
    for f in sorted(root.glob("*.yaml")):
        data = yaml.safe_load(f.read_text())
        cases.append(Case(id=f.stem, category=data["category"], prompt=data["prompt"], rubric=data["rubric"]))
    return cases
