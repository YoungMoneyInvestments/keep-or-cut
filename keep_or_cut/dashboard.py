"""Render the local HTML dashboard. Hero is class × model, not a markdown dump."""
from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from keep_or_cut.classes import skill_family
from keep_or_cut.models import AblationDelta, Profile

KIND_ORDER = ("claude.md", "skills", "hooks", "agents")
_KIND_RANK = {k: i for i, k in enumerate(KIND_ORDER)}

_HIDE_MD_SECTIONS = {
    "profiles",
    "arena-style elo",
    "same model, with vs without the extra context",
    "same model, with vs without",
}


@dataclass
class MatrixCell:
    delta: float | None = None
    recommendation: str = ""
    n_paired: int = 0
    expected: bool = False

    @property
    def css(self) -> str:
        if self.delta is None:
            return "empty"
        if self.n_paired == 0:
            return "empty"
        rec = self.recommendation.upper()
        if rec == "KEEP":
            return "keep"
        if rec == "REMOVE":
            return "remove"
        if rec == "PROMPT_BLOAT":
            return "bloat"
        return "empty"


@dataclass
class MatrixRow:
    id: str
    label: str
    kind: str
    depth: int
    parent: str
    cells: dict[str, MatrixCell] = field(default_factory=dict)
    children: list["MatrixRow"] = field(default_factory=list)

    def mean_delta(self) -> float:
        vals = [c.delta for c in self.cells.values() if c.delta is not None]
        return sum(vals) / len(vals) if vals else 0.0


def short_model(model: str) -> str:
    """Human column label. Never the raw provider id."""
    raw = model.split(":", 1)[-1]
    m = raw.lower()
    if "haiku" in m:
        return "Haiku"
    if "sonnet" in m:
        return "Sonnet"
    if "opus" in m:
        return "Opus"
    if "codex" in m or m.startswith("gpt-") or "gpt-5" in m or "luna" in m:
        return "Codex"
    if "grok" in m:
        return "Grok"
    if "gemini" in m:
        return "Gemini"
    if "cursor" in m:
        return "Cursor"
    return raw.split("/")[-1]


def _model_sort(model: str) -> tuple[int, int, str]:
    label = short_model(model)
    provider = {
        "Haiku": 0,
        "Sonnet": 0,
        "Opus": 0,
        "Codex": 1,
        "Grok": 2,
        "Gemini": 3,
        "Cursor": 4,
    }.get(label, 50)
    tier = {"Haiku": 0, "Sonnet": 1, "Opus": 2}.get(label, 0)
    return (provider, tier, model)


def model_labels(models: list[str]) -> dict[str, str]:
    labels = {m: short_model(m) for m in models}
    counts: dict[str, int] = {}
    for lab in labels.values():
        counts[lab] = counts.get(lab, 0) + 1
    if all(n == 1 for n in counts.values()):
        return labels
    used: dict[str, int] = {}
    out: dict[str, str] = {}
    for m in models:
        lab = labels[m]
        if counts[lab] == 1:
            out[m] = lab
            continue
        used[lab] = used.get(lab, 0) + 1
        out[m] = f"{lab} {used[lab]}"
    return out


def _is_plus_all(name: str) -> bool:
    return name.endswith("+all") or name.endswith("/+all")


def _row_spec(delta: AblationDelta, skill_leaves: list[str]) -> tuple[str, str, str, int, str]:
    """id, label, kind, depth, parent."""
    kind = delta.kind or "bundle"
    name = delta.skill_name
    if _is_plus_all(name):
        return (name, name, kind, 0, "")
    if kind == "claude.md":
        return ("claude.md", "CLAUDE.md", kind, 0, "")
    if kind in ("hooks", "agents"):
        return (kind, kind, kind, 0, "")
    if kind == "skills":
        if name in {"skills", "skills (0)"} or name.startswith("skills ("):
            return ("skills", name if name.startswith("skills (") else "skills", "skills", 0, "")
        leaf = name.split("/")[-1]
        family = skill_family(leaf, skill_leaves)
        row_id = name if name.startswith("skills/") else f"skills/{leaf}"
        if family == f"skills/{leaf}":
            return (row_id, leaf, "skills", 1, "skills")
        return (row_id, leaf, "skills", 2, family)
    return (name, name, kind, 0, "")


def _skill_leaves(deltas: list[AblationDelta]) -> list[str]:
    leaves: list[str] = []
    for d in deltas:
        if d.kind != "skills":
            continue
        if not d.skill_name or d.skill_name == "skills" or d.skill_name.startswith("skills ("):
            continue
        leaves.append(d.skill_name.split("/")[-1])
    return leaves


def _empty_cell(expected: bool) -> MatrixCell:
    return MatrixCell(expected=expected, n_paired=0 if expected else 0)


def build_matrix(
    deltas: list[AblationDelta],
    *,
    profiles: list[Profile] | None = None,
    models: list[str] | None = None,
) -> tuple[list[str], list[MatrixRow]]:
    """Return (model ids in column order, top-level rows with nested children).

    Deltas with no `kind` are dropped when any typed class exists, so +all
    never occupies the hero. Missing expected cells stay empty (no inferred Δ).
    """
    typed = [d for d in deltas if d.kind and not _is_plus_all(d.skill_name)]
    usable = typed if typed else [d for d in deltas if not _is_plus_all(d.skill_name)]

    expected: set[tuple[str, str]] = set()
    if profiles:
        for p in profiles:
            if p.context_dir is None:
                continue
            if not p.kind and typed:
                continue
            rid = p.class_id or p.kind or Path(p.context_dir).name
            if _is_plus_all(p.id) or _is_plus_all(rid):
                continue
            expected.add((p.model, rid))

    model_ids = list(models or [])
    for d in usable:
        if d.model not in model_ids:
            model_ids.append(d.model)
    for model, _rid in expected:
        if model not in model_ids:
            model_ids.append(model)
    model_ids = sorted(model_ids, key=_model_sort)

    leaves = _skill_leaves(usable)
    by_id: dict[str, MatrixRow] = {}
    for d in usable:
        rid, label, kind, depth, parent = _row_spec(d, leaves)
        row = by_id.get(rid)
        if row is None:
            row = MatrixRow(rid, label, kind, depth, parent)
            by_id[rid] = row
        rec = d.recommendation if d.n_paired else ""
        row.cells[d.model] = MatrixCell(
            delta=d.delta if d.n_paired else None,
            recommendation=rec,
            n_paired=d.n_paired,
            expected=True,
        )

    for model, rid in expected:
        if rid not in by_id:
            label = "CLAUDE.md" if rid == "claude.md" else rid.split("/")[-1]
            kind = rid if rid in _KIND_RANK else (
                "skills" if rid.startswith("skills") else rid
            )
            depth = 0 if rid in _KIND_RANK or rid == "skills" else (2 if "-" in rid.split("/")[-1] else 1)
            parent = "" if depth == 0 else "skills"
            if rid.startswith("skills/") and rid != "skills":
                leaf = rid.split("/")[-1]
                fam = skill_family(leaf, leaves or [leaf])
                depth = 1 if fam == rid else 2
                parent = "skills" if depth == 1 else fam
                kind = "skills"
            by_id[rid] = MatrixRow(rid, label, kind, depth, parent)
        if model not in by_id[rid].cells:
            by_id[rid].cells[model] = MatrixCell(expected=True, n_paired=0)

    # Synthesize missing family / skills parents so children can nest. Repeat until
    # every ancestor resolves: a synthesized family row (e.g. "skills/example") has
    # its own parent ("skills"), which can itself still be missing. A single pass
    # only fixed one level and left orphaned rows with no root, so the dashboard
    # rendered an empty table for any --split skills matrix with a shared prefix.
    added = True
    while added:
        added = False
        for row in list(by_id.values()):
            if row.parent and row.parent not in by_id:
                parent_label = (
                    "skills" if row.parent == "skills" else row.parent.split("/")[-1]
                )
                by_id[row.parent] = MatrixRow(
                    row.parent,
                    parent_label,
                    "skills",
                    0 if row.parent == "skills" else 1,
                    "" if row.parent == "skills" else "skills",
                )
                added = True

    for row in by_id.values():
        for m in model_ids:
            if m not in row.cells:
                row.cells[m] = _empty_cell(False)

    # Roll child means up to a synthesized parent that has no own measurements.
    for row in by_id.values():
        kids = [c for c in by_id.values() if c.parent == row.id]
        if not kids:
            continue
        if row.id == "skills" and not row.label.startswith("skills ("):
            n_skills = len({k.id for k in by_id.values() if k.kind == "skills" and k.depth > 0})
            if n_skills:
                row.label = f"skills ({n_skills})"
        own = any(c.delta is not None for c in row.cells.values())
        if own:
            continue
        for m in model_ids:
            child_vals = [k.cells[m].delta for k in kids if k.cells[m].delta is not None]
            if not child_vals:
                continue
            mean = round(sum(child_vals) / len(child_vals), 2)
            if mean >= 1.5:
                rec = "KEEP"
            elif mean <= -1.0:
                rec = "REMOVE"
            else:
                rec = "PROMPT_BLOAT"
            n = min((k.cells[m].n_paired for k in kids if k.cells[m].delta is not None), default=0)
            row.cells[m] = MatrixCell(delta=mean, recommendation=rec, n_paired=n, expected=True)

    roots = [r for r in by_id.values() if not r.parent]
    child_map: dict[str, list[MatrixRow]] = {}
    for row in by_id.values():
        if row.parent:
            child_map.setdefault(row.parent, []).append(row)
    for row in by_id.values():
        kids = child_map.get(row.id, [])
        kids.sort(key=lambda r: (r.mean_delta(), r.id))
        row.children = kids

    def _root_key(r: MatrixRow) -> tuple[int, float, str]:
        return (_KIND_RANK.get(r.kind, 40), r.mean_delta(), r.id)

    roots.sort(key=_root_key)
    return model_ids, roots


def _walk(rows: list[MatrixRow]) -> list[MatrixRow]:
    out: list[MatrixRow] = []
    for row in rows:
        out.append(row)
        out.extend(_walk(row.children))
    return out


def _parse_md_tables(md: str) -> list[tuple[str, list[str], list[list[str]]]]:
    """Return [(section_title, headers, rows), ...] for markdown pipe tables."""
    sections: list[tuple[str, list[str], list[list[str]]]] = []
    current_title = "Leaderboard"
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            current_title = line[3:].strip()
            i += 1
            continue
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1]):
            headers = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            sections.append((current_title, headers, rows))
            continue
        i += 1
    return sections


def _cell_class(text: str) -> str:
    t = text.upper()
    if "KEEP" in t or "✅" in text:
        return "keep"
    if "REMOVE" in t or "❌" in text:
        return "remove"
    if "PROMPT_BLOAT" in t or "🧹" in text:
        return "bloat"
    if text.startswith("+"):
        return "pos"
    if text.startswith("-") and re.match(r"^-\d", text):
        return "neg"
    return ""


def _banner_for(status: str, missing: list[str] | None) -> str:
    if status == "incomplete":
        listed = ""
        if missing:
            items = "".join(f"<li><code>{html.escape(m)}</code></li>" for m in missing[:40])
            more = f"<li>… {len(missing) - 40} more</li>" if len(missing) > 40 else ""
            listed = f"<ul class='missing'>{items}{more}</ul>"
        return (
            "<div class='banner' role='alert'>"
            "<strong>Matrix incomplete — no KEEP / PROMPT_BLOAT / REMOVE.</strong>"
            f"{listed}</div>"
        )
    if status == "unpaired":
        return (
            "<div class='banner' role='alert'>"
            "<strong>No paired cases — no call.</strong> "
            "Bare and with-context have to share the same case ids."
            "</div>"
        )
    if status == "empty":
        return (
            "<div class='banner'>"
            "No results yet. "
            "<code>python3 -m keep_or_cut.cli --context-dir ~/.claude</code>"
            "</div>"
        )
    return ""


def _css() -> str:
    return """
:root {
  --bg:#0b0d10; --panel:#12151a; --ink:#e8edf5; --muted:#9aa3b2;
  --line:#2a3038; --keep:#1f6f4a; --bloat:#8a6a1f; --remove:#8b2e2e;
  --pos:#3d9b6e; --neg:#c45c5c; --gold:#e8a54b; --gold-ink:#1a1206;
}
* { box-sizing: border-box; }
html, body { margin:0; background: var(--bg); color: var(--ink); }
body {
  min-height: 100vh;
  font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
header { padding: 28px 28px 12px; display:grid; gap:10px; }
.wordmark { margin:0; font-size: 22px; font-weight: 650; letter-spacing: -0.03em; color: var(--gold); }
.meta { margin:0; color: var(--muted); font-size: 13px; display:flex; flex-wrap:wrap; gap:10px 18px; }
.meta code { color: var(--ink); }
.legend { margin:0; padding:0; list-style:none; display:flex; flex-wrap:wrap; gap:8px; }
.legend li {
  display:inline-flex; align-items:center; gap:8px;
  padding: 4px 10px; border-radius: 999px; font-size: 12px; letter-spacing: 0.04em;
  text-transform: uppercase; font-weight: 600;
}
.legend .swatch { width:10px; height:10px; border-radius: 2px; display:inline-block; }
.legend .keep { background: color-mix(in srgb, var(--keep) 35%, var(--panel)); color:#b8f0d0; }
.legend .bloat { background: color-mix(in srgb, var(--bloat) 35%, var(--panel)); color:#f3dd8a; }
.legend .remove { background: color-mix(in srgb, var(--remove) 35%, var(--panel)); color:#f5b4b4; }
.legend .empty { background: var(--panel); color: var(--muted); border:1px solid var(--line); }
.banner {
  margin: 0 28px; padding: 12px 14px;
  background: color-mix(in srgb, var(--remove) 22%, var(--panel));
  border: 1px solid color-mix(in srgb, var(--remove) 55%, var(--line));
  border-radius: 10px;
}
.banner ul { margin: 8px 0 0; padding-left: 18px; }
main { padding: 16px 28px 40px; }
.matrix { border:1px solid var(--line); border-radius: 12px; overflow:auto; background: var(--panel); }
table { width:100%; border-collapse: collapse; min-width: 560px; }
th, td { border-bottom:1px solid var(--line); padding: 10px 12px; }
th { color: var(--muted); font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase; font-weight: 650; }
th.model { text-align: center; }
td.rowhead { text-align:left; white-space: nowrap; font-weight: 600; }
td.rowhead.depth-1 { padding-left: 28px; color: #cfd6e2; }
td.rowhead.depth-2 { padding-left: 46px; color: #b7c0ce; font-weight: 500; }
button.branch {
  appearance:none; background:transparent; border:0; color: inherit;
  font: inherit; font-weight: 650; cursor:pointer; padding: 0 0 0 2px;
}
button.branch:focus-visible { outline: 2px solid var(--gold); outline-offset: 3px; }
button.branch .chev { display:inline-block; width: 1em; color: var(--gold); }
td.cell { text-align:center; min-width: 92px; vertical-align: middle; }
td.cell .delta {
  display:block; font-size: 18px; font-weight: 700;
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em;
}
td.cell .call { display:block; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; margin-top: 2px; }
td.keep { background: color-mix(in srgb, var(--keep) 48%, var(--panel)); color: #d8ffe8; }
td.bloat { background: color-mix(in srgb, var(--bloat) 42%, var(--panel)); color: #ffe9a8; }
td.remove { background: color-mix(in srgb, var(--remove) 48%, var(--panel)); color: #ffd0d0; }
td.empty { color: var(--muted); background: transparent; }
footer { padding: 0 28px 28px; color: var(--muted); font-size: 12px; max-width: 78ch; }
@media (max-width: 700px) {
  header, main, footer, .banner { padding-left: 16px; padding-right: 16px; }
  td.cell .delta { font-size: 16px; }
}
""".strip()


def _render_cell(cell: MatrixCell) -> str:
    if cell.delta is None or cell.n_paired == 0:
        label = "— N=0" if cell.expected else "—"
        return f'<td class="cell empty"><span class="delta">{label}</span></td>'
    rec = html.escape(cell.recommendation)
    delta = f"{cell.delta:+.2f}"
    return (
        f'<td class="cell {cell.css}">'
        f'<span class="delta">{delta}</span>'
        f'<span class="call">{rec}</span>'
        f"</td>"
    )


def _render_matrix(models: list[str], roots: list[MatrixRow], labels: dict[str, str]) -> str:
    parts = ['<div class="matrix"><table>', "<thead><tr>", '<th scope="col">Class</th>']
    for m in models:
        parts.append(f'<th class="model" scope="col">{html.escape(labels[m])}</th>')
    parts.append("</tr></thead><tbody>")
    for row in _walk(roots):
        has_kids = bool(row.children)
        hidden = ' hidden' if row.depth > 0 else ""
        parent_attr = f' data-parent="{html.escape(row.parent)}"' if row.parent else ""
        parts.append(f'<tr class="depth-{row.depth}"{hidden}{parent_attr}>')
        if has_kids:
            parts.append(
                f'<td class="rowhead depth-{row.depth}">'
                f'<button type="button" class="branch" data-toggle="{html.escape(row.id)}" '
                f'aria-expanded="false"><span class="chev">▸</span> {html.escape(row.label)}</button>'
                "</td>"
            )
        else:
            parts.append(
                f'<td class="rowhead depth-{row.depth}">{html.escape(row.label)}</td>'
            )
        for m in models:
            parts.append(_render_cell(row.cells[m]))
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    parts.append(
        """<script>
(() => {
  const buttons = [...document.querySelectorAll("button.branch")];
  const closeUnder = (id) => {
    document.querySelectorAll(`tr[data-parent="${id}"]`).forEach((tr) => {
      tr.hidden = true;
      const nested = tr.querySelector("button.branch");
      if (nested) {
        nested.setAttribute("aria-expanded", "false");
        closeUnder(nested.getAttribute("data-toggle"));
      }
    });
  };
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-toggle");
      const open = btn.getAttribute("aria-expanded") === "true";
      const row = btn.closest("tr");
      const parent = row && row.getAttribute("data-parent");
      const scope = parent
        ? [...document.querySelectorAll(`tr[data-parent="${parent}"] button.branch`)]
        : buttons.filter((b) => !b.closest("tr").getAttribute("data-parent"));
      scope.forEach((other) => {
        if (other === btn) return;
        other.setAttribute("aria-expanded", "false");
        const chev = other.querySelector(".chev");
        if (chev) chev.textContent = "▸";
        closeUnder(other.getAttribute("data-toggle"));
      });
      btn.setAttribute("aria-expanded", open ? "false" : "true");
      const chev = btn.querySelector(".chev");
      if (chev) chev.textContent = open ? "▸" : "▾";
      document.querySelectorAll(`tr[data-parent="${id}"]`).forEach((tr) => {
        tr.hidden = open;
      });
      if (open) closeUnder(id);
    });
  });
})();
</script>"""
    )
    return "\n".join(parts)


def render_html(
    md: str = "",
    *,
    title: str = "keep-or-cut",
    source: str = "",
    deltas: list[AblationDelta] | None = None,
    profiles: list[Profile] | None = None,
    models: list[str] | None = None,
    home: str = "",
    n_cases: int | None = None,
    status: str = "complete",
    missing: list[str] | None = None,
) -> str:
    matrix_models, roots = build_matrix(deltas or [], profiles=profiles, models=models)
    labels = model_labels(matrix_models)
    if status == "complete" and not roots:
        status = "empty" if not md else status

    providers = []
    for lab in labels.values():
        if lab.startswith("Haiku") or lab.startswith("Sonnet") or lab.startswith("Opus"):
            tag = "Claude"
        elif lab.startswith("Codex"):
            tag = "Codex"
        elif lab.startswith("Grok"):
            tag = "Grok"
        elif lab.startswith("Gemini"):
            tag = "Gemini"
        elif lab.startswith("Cursor"):
            tag = "Cursor"
        else:
            continue
        if tag not in providers:
            providers.append(tag)

    meta_bits = []
    if home:
        meta_bits.append(f"<span>home <code>{html.escape(home)}</code></span>")
    if providers:
        meta_bits.append(f"<span>{html.escape(' · '.join(providers))}</span>")
    elif matrix_models:
        meta_bits.append(f"<span>{len(matrix_models)} models</span>")
    if n_cases is not None:
        meta_bits.append(f"<span>{n_cases} cases</span>")
    if source:
        meta_bits.append(f"<span class='src'>from <code>{html.escape(source)}</code></span>")

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1" />',
        f"<title>{html.escape(title)}</title>",
        f"<style>{_css()}</style>",
        "</head>",
        "<body>",
        "<!-- THESIS: the page is a class × model scorecard. Categories as rows, models as columns, Δ plus call in the cell. -->",
        "<header>",
        f'<p class="wordmark">{html.escape(title)}</p>',
        f'<p class="meta">{"".join(meta_bits) if meta_bits else "Each class scored alone against bare."}</p>',
        '<ul class="legend">',
        '<li class="keep"><span class="swatch" style="background:#1f6f4a"></span>KEEP Δ≥+1.5</li>',
        '<li class="bloat"><span class="swatch" style="background:#8a6a1f"></span>PROMPT_BLOAT</li>',
        '<li class="remove"><span class="swatch" style="background:#8b2e2e"></span>REMOVE Δ≤−1.0</li>',
        '<li class="empty"><span class="swatch" style="background:#2a3038"></span>— N=0</li>',
        "</ul>",
        "</header>",
        _banner_for(status, missing),
        "<main>",
    ]
    if roots:
        parts.append(_render_matrix(matrix_models, roots, labels))
    elif md:
        sections = [
            (t, h, r)
            for t, h, r in _parse_md_tables(md)
            if t.strip().lower() not in _HIDE_MD_SECTIONS
        ]
        if not sections:
            parts.append(
                "<p>No class × model table in this leaderboard. Re-run with "
                "<code>--split classes</code> (or <code>auto</code> on a Claude/Codex/Grok home).</p>"
            )
        for sec_title, headers, rows in sections:
            parts.append(f"<h2>{html.escape(sec_title)}</h2>")
            parts.append('<div class="matrix"><table><thead><tr>')
            for h in headers:
                parts.append(f"<th>{html.escape(h.replace('`', ''))}</th>")
            parts.append("</tr></thead><tbody>")
            for row in rows:
                parts.append("<tr>")
                for cell in row:
                    cls = _cell_class(cell)
                    shown = html.escape(cell.replace("**", "").replace("`", ""))
                    parts.append(f'<td class="cell {cls}">{shown}</td>')
                parts.append("</tr>")
            parts.append("</tbody></table></div>")
    else:
        parts.append(
            "<p>No class × model cells yet. "
            "<code>python3 -m keep_or_cut.cli --context-dir ~/.claude</code></p>"
        )
    parts.extend(
        [
            "</main>",
            "<footer>Each class is scored alone against bare. Read down a column: "
            "if a stronger model is worse on the same class, that class is what to cut first. "
            "KEEP / PROMPT_BLOAT / REMOVE are only printed on a complete paired matrix.</footer>",
            "</body></html>",
        ]
    )
    return "\n".join(parts)


def write_dashboard(
    leaderboard_path: Path | None,
    out_path: Path,
    *,
    deltas: list[AblationDelta] | None = None,
    profiles: list[Profile] | None = None,
    models: list[str] | None = None,
    home: str = "",
    n_cases: int | None = None,
    status: str = "complete",
    missing: list[str] | None = None,
) -> Path:
    md = ""
    source = ""
    if leaderboard_path is not None and Path(leaderboard_path).is_file():
        leaderboard_path = Path(leaderboard_path)
        md = leaderboard_path.read_text()
        source = str(leaderboard_path)
    html_doc = render_html(
        md,
        title="keep-or-cut",
        source=source,
        deltas=deltas,
        profiles=profiles,
        models=models,
        home=home,
        n_cases=n_cases,
        status=status,
        missing=missing,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc)
    meta = {
        "leaderboard": source,
        "dashboard": str(out_path),
        "status": status,
        "home": home,
        "n_cases": n_cases,
        "n_deltas": len(deltas or []),
    }
    out_path.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    return out_path


def main() -> None:
    p = argparse.ArgumentParser(description="Render keep-or-cut HTML dashboard")
    p.add_argument("--leaderboard", default=None, help="Path to leaderboard_*.md")
    p.add_argument("--results-dir", default="results")
    p.add_argument("--out", default="results/dashboard.html")
    args = p.parse_args()

    if args.leaderboard:
        board = Path(args.leaderboard)
    else:
        boards = sorted(Path(args.results_dir).glob("leaderboard_*.md"))
        board = boards[-1] if boards else None
        if board is None:
            write_dashboard(None, Path(args.out), status="empty")
            print(args.out)
            return
    out = write_dashboard(board, Path(args.out))
    print(out)


if __name__ == "__main__":
    main()
