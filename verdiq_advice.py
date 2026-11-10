"""Suggest a realistic package of design changes that closes the score gap and the failing balancing groups.

Order of preference (cheapest, least disruptive first):
  1. Add qualities on top of green surfaces that already exist (e.g. field-layer diversity on planting beds);
     together they never cover more than the planting itself, and none takes more than a realistic share
  2. Add elements (trees, nest boxes) within sensible limits
  3. Convert low-value surfaces into higher-value ones on the same level (e.g. paving -> planting), keeping
     most of the paving for paths and access; preserved or existing features are never "created"
A quality whose surface is missing (green-roof qualities without a green roof, slab beds without beds) is never
proposed (rulebook spatial.quality_requires).
Then make sure each failing balancing group gets the missing number of new qualities.
Every package is re-calculated with the real engine, so the predicted result is exact.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from verdiq_calculator import Result, calculate
from verdiq_schema import Rulebook


@dataclass(frozen=True)
class Step:
    kind: str                  # 'quality' | 'element' | 'convert' | 'balance'
    factor_id: str
    label: str
    quantity: float
    unit: str                  # 'm²' | 'st'
    points: float
    from_factor_id: str | None = None
    from_label: str | None = None
    adds_groups: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        q = f"{self.quantity:,.0f} m²" if self.unit == "m²" else f"{int(self.quantity)} st"
        if self.kind == "convert":
            return f"Convert {q} of {self.from_label} into {self.label}"
        return f"Add {q} of {self.label}"


@dataclass
class Package:
    steps: list[Step] = field(default_factory=list)
    inputs: dict[str, float] = field(default_factory=dict)
    result: Result | None = None
    closes_score: bool = False
    closes_balancing: bool = False
    remaining_note: str | None = None


def _green_area(rb: Rulebook, q: dict[str, float]) -> float:
    """Planted base area (ground + roofs) that can carry qualities like field-layer diversity."""
    return sum(v for k, v in q.items()
               if rb.factor(k).kind == "base" and rb.factor(k).measure == "area" and rb.factor(k).factor >= 0.3)


def _apply(q: dict[str, float], s: Step) -> dict[str, float]:
    new = dict(q)
    new[s.factor_id] = new.get(s.factor_id, 0) + s.quantity
    if s.from_factor_id:
        new[s.from_factor_id] = max(0.0, new.get(s.from_factor_id, 0) - s.quantity)
    return {k: v for k, v in new.items() if v}


# Realistic ceiling for a planting quality, as a share of all planting: a butterfly bed or a flower meadow is a
# feature, not the whole courtyard. Others default to half the planting.
QUALITY_MAX_SHARE = {"butterfly_bed": 0.10, "flower_display": 0.25, "shrubs_berry": 0.15, "shrubs_experience": 0.25,
                     "shrubs_edible": 0.15}


MAX_CONVERT_SHARE = 0.4     # at most 40 % of a surface is converted; the rest stays (paths, access, fire lanes)


def _creatable(fid: str) -> bool:
    return not any(w in fid for w in ("preserved", "existing", "old_", "_old"))


def _feasible(rb: Rulebook, fid: str, q: dict[str, float]) -> bool:
    req = rb.spatial.quality_requires.get(fid) if rb.spatial else None
    return not req or any(q.get(r, 0) > 0 for r in req)


def suggest_package(rb: Rulebook, inputs: dict[str, float], plot_area: float, calc_kwargs: dict | None = None,
                    *, lang: str = "en", max_elements_per_factor: int = 6, max_steps: int = 12) -> Package:
    kw = dict(calc_kwargs or {})
    lab = lambda fid: rb.factor(fid).label.text(lang)  # noqa: E731
    q = {k: float(v) for k, v in inputs.items() if v}
    q0 = dict(q)
    res = calculate(rb, q, plot_area, **kw)
    pkg = Package(inputs=q, result=res)
    if res.target is None:
        pkg.remaining_note = "Enter the inputs that set the target first."
        return pkg

    def gap(r):
        return r.shortfall_points

    # ---------- 1-3: close the score gap greedily
    for _ in range(max_steps):
        g = gap(res)
        if g <= 1e-6:
            break
        cands: list[tuple[int, float, Step]] = []
        green = _green_area(rb, q)
        failing = {x.id for x in res.balancing if x.passed is False}
        pq = set(rb.spatial.planting_qualities) if rb.spatial else set()
        planting_used = sum(v for k, v in q.items() if k in pq)
        for f in rb.factors:
            if f.factor <= 0 or not _feasible(rb, f.id, q) or not _creatable(f.id):
                continue
            new_groups = tuple(x for x in f.groups if x in failing and f.id not in q)
            if f.kind == "supplementary" and f.measure == "area" and green > 0 and rb.spatial \
                    and f.id in rb.spatial.planting_qualities:
                # keep 20 % of the planting free so balancing can still add the qualities it needs
                room = min(QUALITY_MAX_SHARE.get(f.id, 0.5) * green - q.get(f.id, 0), 0.8 * green - planting_used)
                if room <= 1:
                    continue
                need = min(room, math.ceil(g / f.factor + 0.5))
                mins = [c.value for c in f.constraints if c.type == "min_area"]
                if mins and need < mins[0] <= room:
                    need = mins[0]
                cands.append((0, -f.factor, Step("quality", f.id, lab(f.id), round(need, 1), "m²", need * f.factor,
                                                adds_groups=new_groups)))
            elif f.kind == "supplementary" and f.measure == "count":
                cap = min([max_elements_per_factor] + [c.value for c in f.constraints if c.type == "max_count"])
                room = cap - q.get(f.id, 0)
                if room < 1:
                    continue
                per = f.unit_area_m2 * f.factor
                n = int(min(room, math.ceil(g / per)))
                cands.append((1, -per, Step("element", f.id, lab(f.id), n, "st", n * per, adds_groups=new_groups)))
        sp = rb.spatial
        levels = [sp.ground_partition, sp.roof] if sp else []
        for level in levels:
            for src_id in level:
                if src_id not in q:
                    continue
                src = rb.factor(src_id)
                left = q[src_id] - (1 - MAX_CONVERT_SHARE) * q0.get(src_id, 0)
                if left <= 1:
                    continue
                for dst_id in level:
                    dst = rb.factor(dst_id)
                    if dst.factor <= src.factor or not _creatable(dst_id):
                        continue
                    area = min(left, math.ceil(g / (dst.factor - src.factor)))
                    cands.append((2, -(dst.factor - src.factor), Step(
                        "convert", dst_id, lab(dst_id), round(area, 1), "m²", area * (dst.factor - src.factor),
                        src_id, lab(src_id), tuple(x for x in dst.groups if x in failing and dst_id not in q))))
        if not cands:
            break
        # prefer steps that also add failing groups, then the cheaper kind of change, then the strongest factor
        cands.sort(key=lambda c: (c[0] - 0.5 * len(c[2].adds_groups), c[1]))
        step = cands[0][2]
        q = _apply(q, step)
        res = calculate(rb, q, plot_area, **kw)
        pkg.steps.append(step)

    # ---------- 4: balancing - add the missing number of new qualities per failing group
    for _ in range(sum(g.max for g in res.balancing) + 1):
        failing = [x for x in res.balancing if x.passed is False]
        if not failing:
            break
        grp = failing[0]
        green = _green_area(rb, q)
        options = []
        excl_used = {i for i, s in enumerate(rb.balancing.exclusive_sets) if any(x in q for x in s.ids)}
        excl_of = {x: i for i, s in enumerate(rb.balancing.exclusive_sets) for x in s.ids}
        for f in rb.factors:
            if grp.id not in f.groups or f.id in q or f.factor < 0 or not _feasible(rb, f.id, q) or not _creatable(f.id):
                continue
            if f.id in excl_of and excl_of[f.id] in excl_used:
                continue                       # another option of the same exclusive set already counts
            others = sum(1 for x in failing if x.id in f.groups)
            if f.measure == "count":
                n = 1
                options.append((-others, 0, n * f.unit_area_m2, Step("balance", f.id, lab(f.id), n, "st",
                                                                    n * f.unit_area_m2 * f.factor,
                                                                    adds_groups=tuple(x.id for x in failing if x.id in f.groups))))
            else:
                a = max([c.value for c in f.constraints if c.type == "min_area"] or [10.0])
                if f.kind == "base":
                    continue   # a new surface type needs re-planning; leave to the designer
                if a > max(green, 10):
                    continue
                pq = set(rb.spatial.planting_qualities) if rb.spatial else set()
                if f.id in pq and sum(v for k, v in q.items() if k in pq) + a > green:
                    continue           # all planting already carries a quality
                options.append((-others, 1, a, Step("balance", f.id, lab(f.id), a, "m²", a * f.factor,
                                                    adds_groups=tuple(x.id for x in failing if x.id in f.groups))))
        if not options:
            pkg.remaining_note = f"No simple addition fixes balancing group {grp.name}; review the design with the landscape architect."
            break
        options.sort(key=lambda o: (o[0], o[1], o[2]))
        step = options[0][3]
        q = _apply(q, step)
        res = calculate(rb, q, plot_area, **kw)
        pkg.steps.append(step)

    # merge repeated steps on the same factor
    merged: dict[tuple, Step] = {}
    for s in pkg.steps:
        k = (s.kind if s.kind != "balance" else "quality", s.factor_id, s.from_factor_id)
        if k in merged:
            m = merged[k]
            merged[k] = Step(m.kind, m.factor_id, m.label, m.quantity + s.quantity, m.unit, m.points + s.points,
                             m.from_factor_id, m.from_label, tuple(sorted(set(m.adds_groups) | set(s.adds_groups))))
        else:
            merged[k] = s
    pkg.steps = list(merged.values())
    pkg.inputs, pkg.result = q, res
    pkg.closes_score = bool(res.passed_target)
    pkg.closes_balancing = res.passed_balancing is True or not res.balancing
    return pkg
