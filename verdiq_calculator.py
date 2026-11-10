"""Verdiq calculation engine: one rulebook + quantities -> score, target, balancing, audit trail.

Pure Python, no Streamlit imports, so the same code runs in the app, in tests and behind an API.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from verdiq_schema import Rulebook

EPS = 1e-9


@dataclass(frozen=True)
class LineItem:
    factor_id: str
    label: str
    kind: str
    section: str
    input_value: float          # m2, or count for count factors
    unit_area_m2: float | None  # area per counted element
    quantity_m2: float          # area entering the formula
    factor: float
    points: float               # quantity_m2 * factor ("ekoeffektiv yta")
    groups: tuple[str, ...]


@dataclass(frozen=True)
class GroupResult:
    id: str
    name: str
    achieved: int
    max: int
    share: float
    min_share: float | None
    passed: bool | None
    indicative: bool = False    # True when the city's exact counting rule is not encoded yet


@dataclass(frozen=True)
class Message:
    severity: str               # 'info' | 'warning' | 'error'
    factor_id: str | None
    text: str


@dataclass
class Result:
    rulebook_id: str
    rulebook_version: str
    rulebook_status: str
    rulebook_sha: str | None
    plot_area_m2: float
    total_points: float
    score: float
    score_unrounded: float
    target: float | None
    target_source: str
    passed_target: bool | None
    balancing_method: str
    balancing_status: str
    balancing: list[GroupResult]
    passed_balancing: bool | None
    passed: bool | None
    line_items: list[LineItem]
    messages: list[Message] = field(default_factory=list)
    template_compat: bool = False

    @property
    def shortfall_points(self) -> float:
        if self.target is None:
            return 0.0
        return max(0.0, self.target * self.plot_area_m2 - self.total_points)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["shortfall_points"] = self.shortfall_points
        return d


def _target(rb: Rulebook, built_share_pct, target_override, variant, msgs):
    t = rb.targets
    min_share = None
    if target_override is not None:
        if not t.allow_project_override:
            raise ValueError("This rulebook does not allow a project-specific target")
        target, source = float(target_override), "project_override"
    elif t.type == "fixed":
        target, source = t.target, "fixed"
    else:
        if built_share_pct is None:
            msgs.append(Message("warning", None, f"Target depends on '{t.by}'; enter it to get a target."))
            return None, "missing_input", None
        row = next((r for r in t.table if r.matches(float(built_share_pct))), None)
        if row is None:
            raise ValueError(f"No target row matches {t.by}={built_share_pct}")
        target, source, min_share = row.target, f"lookup:{t.by}={built_share_pct}", row.balancing_min_share
    if variant:
        v = t.variants.get(variant)
        if v is None:
            raise ValueError(f"Unknown target variant '{variant}'")
        min_share = v.get("balancing_min_share", min_share)
        if "target" in v and target_override is None:
            target = v["target"]
        source += f"+variant:{variant}"
    return target, source, min_share


def calculate(rulebook: Rulebook, inputs: dict[str, float], plot_area_m2: float, *,
              built_share_pct: float | None = None, target_override: float | None = None,
              balancing_min_share_override: float | None = None, variant: str | None = None,
              template_compat: bool = False, rulebook_sha: str | None = None, lang: str = "en") -> Result:
    """Calculate a green area factor for one design option under one rulebook.

    inputs: factor id -> m2 (area factors) or number of elements (count factors).
    template_compat: reproduce the municipality's Excel template where it deviates from the guide.
    """
    if not plot_area_m2 or plot_area_m2 <= 0:
        raise ValueError("Plot area must be positive")
    unknown = set(inputs) - {f.id for f in rulebook.factors}
    if unknown:
        raise ValueError(f"Unknown factor ids for {rulebook.key}: {sorted(unknown)}")

    msgs: list[Message] = []
    items: list[LineItem] = []
    used: dict[str, float] = {}
    present = {k for k, v in inputs.items() if v and float(v) > 0}
    for f in rulebook.factors:
        v = float(inputs.get(f.id, 0) or 0)
        if v < 0:
            raise ValueError(f"{f.id}: negative quantity")
        dep = next((c for c in f.constraints if c.type == "requires_any"), None)
        if v and dep and not (set(dep.of) & present):
            needs = ", ".join(rulebook.factor(x).label.text(lang) for x in dep.of)
            msgs.append(Message("warning", f.id, f"Scores 0: this only counts together with one of: {needs}"))
            continue
        for c in f.constraints:
            if c.type == "max_count" and v > c.value:
                msgs.append(Message(c.severity, f.id, (c.text or f"Max {c.value:g}") + f" - capped at {c.value:g}"))
                v = float(c.value)
        if v == 0:
            continue
        unit = None
        if f.measure == "count":
            unit = f.template_unit_area_m2 if (template_compat and f.template_unit_area_m2) else f.unit_area_m2
            q = v * unit
        else:
            q = v
        used[f.id] = v
        items.append(LineItem(f.id, f.label.text(lang), f.kind, f.section, v, unit, q, f.factor,
                              q * f.factor, tuple(f.groups)))
        if f.template_unit_area_m2 and not template_compat:
            msgs.append(Message("info", f.id, f"City template uses {f.template_unit_area_m2:g} m2 per element; "
                                              f"guide says {f.unit_area_m2:g} m2. Verdiq follows the guide."))

    # constraints that look at the whole option
    for f in rulebook.factors:
        if f.id not in used:
            continue
        for c in f.constraints:
            if c.type == "min_area" and used[f.id] < c.value:
                msgs.append(Message(c.severity, f.id, c.text or f"Minimum {c.value:g} m2"))
            if c.type == "requires_total":
                tot = sum(used.get(x, 0) for x in c.of)
                if tot < c.min_value:
                    msgs.append(Message(c.severity, f.id, (c.text or "Requirement not met") + f" (has {tot:g})"))
        for x in f.excludes:
            if x in used:
                msgs.append(Message("info", f.id, f"May not be counted on the same area as '{x}' - check they are separate surfaces"))
    for s in rulebook.balancing.exclusive_sets:
        n = sum(1 for x in s.ids if x in used)
        if n > 1:
            msgs.append(Message("warning", None, (s.text or "Only one of these may be chosen") + f": {', '.join(x for x in s.ids if x in used)}"))

    total = sum(i.points for i in items)
    score_raw = total / plot_area_m2
    score = round(score_raw, rulebook.score.rounding)
    target, target_source, row_min_share = _target(rulebook, built_share_pct, target_override, variant, msgs)

    groups, bal_pass = _balancing(rulebook, used, row_min_share, balancing_min_share_override, template_compat, lang, msgs)
    passed_target = None if target is None else score_raw + EPS >= target
    passed = None if (passed_target is None or bal_pass is None) else (passed_target and bal_pass)
    if any(m.severity == "error" for m in msgs) and passed:
        passed = False

    return Result(rulebook.meta.id, rulebook.meta.version, rulebook.meta.status, rulebook_sha, float(plot_area_m2),
                  total, score, score_raw, target, target_source, passed_target, rulebook.balancing.method,
                  rulebook.balancing.status, groups, bal_pass, passed, items, msgs, template_compat)


def _balancing(rb: Rulebook, used: dict[str, float], row_min_share, override, template_compat, lang, msgs):
    b = rb.balancing
    if b.method == "none":
        return [], True
    indicative = b.method == "est_matrix" and not (isinstance(b.est_matrix, dict) and b.est_matrix)
    if indicative:
        msgs.append(Message("warning", None, "Balancing is indicative: the city counts individual ecosystem services "
                                             "per factor and that matrix is not yet encoded. Verify in the city template."))
    excl = {x: i for i, s in enumerate(b.exclusive_sets) for x in s.ids} if not template_compat else {}
    results = []
    for g in b.groups:
        members = [f for f in rb.factors if g.id in f.groups]
        if indicative:
            mx = _count(members, excl, None)
        else:
            mx = g.max_count if g.max_count is not None else _count(members, excl, None)
        achieved = _count(members, excl, used)
        share = achieved / mx if mx else 0.0
        min_share = override if override is not None else (g.min_share if g.min_share is not None else row_min_share)
        ok = None if (min_share is None or indicative) else share + EPS >= min_share
        results.append(GroupResult(g.id, g.name.text(lang), achieved, mx, share, min_share, ok, indicative))
    if not b.required:
        return results, True          # reported only: balancing does not decide pass/fail
    oks = [r.passed for r in results]
    all_pass = False if False in oks else (None if None in oks else True)
    return results, all_pass


def _count(members, excl, used):
    seen_sets, n = set(), 0
    for f in members:
        if used is not None and f.id not in used:
            continue
        if f.id in excl:
            if excl[f.id] in seen_sets:
                continue
            seen_sets.add(excl[f.id])
        n += 1
    return n


def max_counts_from_flags(rb: Rulebook) -> dict[str, int]:
    """Possible count per group derived from factor flags (used to check declared max_count)."""
    excl = {x: i for i, s in enumerate(rb.balancing.exclusive_sets) for x in s.ids}
    return {g.id: _count([f for f in rb.factors if g.id in f.groups], excl, None) for g in rb.balancing.groups}
