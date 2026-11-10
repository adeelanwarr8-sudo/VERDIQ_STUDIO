"""Geometry checks on an imported plan - the errors a city reviewer otherwise finds by hand.

Checks: surfaces outside the plot, overlapping ground surfaces, untagged ground, qualities without a
base surface, elements (trees) outside the surfaces they need, and too-small contiguous areas.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point
from shapely.ops import unary_union

from verdiq_schema import Rulebook

TOL_M2 = 0.5   # ignore slivers below this area (drawing noise)


@dataclass(frozen=True)
class Finding:
    severity: str          # 'info' | 'warning' | 'error'
    code: str              # outside_plot | ground_overlap | untagged_ground | overlay_without_base | not_within | too_small
    factor_id: str | None
    text: str
    area_m2: float | None = None
    location: tuple[float, float] | None = None   # a representative point, for the map
    source: str = "verdiq_check"                  # or 'city_rule'


def _geoms_by_factor(rb, stats, mapping):
    out: dict[str, list] = {}
    pts: dict[str, list] = {}
    for layer, fid in mapping.items():
        if not fid or layer not in stats:
            continue
        s = stats[layer]
        measure = rb.factor(fid).measure
        out.setdefault(fid, []).extend(s.geoms + (getattr(s, "circles", []) if measure == "area" else []))
        if measure == "count":
            pts.setdefault(fid, []).extend(s.points)
    return {k: unary_union(v) for k, v in out.items() if v}, pts


def check_plan(rb: Rulebook, stats: dict, mapping: dict[str, str], plot=None) -> list[Finding]:
    """Run all spatial checks. `plot` is the plot boundary geometry (or None to skip plot checks)."""
    sp = rb.spatial
    geoms, pts = _geoms_by_factor(rb, stats, mapping)
    out: list[Finding] = []
    label = lambda fid: rb.factor(fid).label.text("sv" if "sv" in rb.meta.languages else "en")  # noqa: E731

    # 1. outside the plot: reported, not counted, and left out of the other checks
    if plot is not None:
        for fid, g in list(geoms.items()):
            outside = g.difference(plot)
            if outside.area > TOL_M2:
                p = outside.representative_point()
                out.append(Finding("info", "outside_plot", fid, f"{label(fid)}: {outside.area:.1f} m² lies outside the plot "
                                   "(legend or neighbouring plot?) and is not counted", outside.area, (p.x, p.y)))
            geoms[fid] = g.intersection(plot)
        for fid, ps in list(pts.items()):
            inside = [(x, y) for x, y in ps if plot.covers(Point(x, y))]
            if len(inside) < len(ps):
                out.append(Finding("info", "outside_plot", fid, f"{label(fid)}: {len(ps) - len(inside)} element(s) outside "
                                   "the plot are not counted"))
            pts[fid] = inside
        geoms = {k: v for k, v in geoms.items() if not v.is_empty}

    if not sp:
        return out

    # 2. ground surfaces must not overlap each other
    ground = [(fid, geoms[fid]) for fid in sp.ground_partition if fid in geoms]
    for i in range(len(ground)):
        for j in range(i + 1, len(ground)):
            (a, ga), (b, gb) = ground[i], ground[j]
            ov = ga.intersection(gb)
            if ov.area > TOL_M2:
                p = ov.representative_point()
                out.append(Finding("error", "ground_overlap", a, f"{label(a)} and {label(b)} overlap by {ov.area:.1f} m²: "
                                   "the same ground is counted twice", ov.area, (p.x, p.y)))

    # 3. untagged ground inside the plot (no score) - informative
    if plot is not None and (ground or sp.roof):
        covered = unary_union([g for _, g in ground] + [geoms[f] for f in sp.roof if f in geoms])
        gap = plot.difference(covered)
        if gap.area > TOL_M2:
            p = gap.representative_point()
            out.append(Finding("info", "untagged_ground", None, f"{gap.area:.1f} m² of the plot has no surface type and scores "
                               "nothing. Tag it (even as sealed) so the plan is complete.", gap.area, (p.x, p.y)))

    # 4. area qualities must sit on a base surface (ground or roof)
    if sp.overlays_on_base:
        base_ids = set(sp.ground_partition) | set(sp.roof)
        base = unary_union([geoms[f] for f in base_ids if f in geoms]) if any(f in geoms for f in base_ids) else None
        for fid, g in geoms.items():
            f = rb.factor(fid)
            if f.kind != "supplementary" or f.measure != "area":
                continue
            loose = g if base is None else g.difference(base)
            if loose.area > TOL_M2 and loose.area > 0.02 * g.area:
                p = loose.representative_point()
                out.append(Finding("warning", "overlay_without_base", fid, f"{label(fid)}: {loose.area:.1f} m² is not on any "
                                   "base surface. Qualities are added on top of a surface type.", loose.area, (p.x, p.y)))

    # 5. elements that must sit within certain surfaces (e.g. trees in deep beds)
    for rule in sp.within_rules:
        allowed = [geoms[f] for f in rule.within if f in geoms]
        allowed_g = unary_union(allowed) if allowed else None
        for fid in rule.factors:
            for x, y in pts.get(fid, []):
                if allowed_g is None or not allowed_g.covers(Point(x, y)):
                    out.append(Finding(rule.severity, "not_within", fid, f"{label(fid)} at ({x:.1f}, {y:.1f}): "
                                       + (rule.text or "not inside an allowed surface"), None, (x, y), rule.source))

    # 6. contiguous area minimums (min_area constraints apply to each separate patch)
    for fid, g in geoms.items():
        for c in rb.factor(fid).constraints:
            if c.type != "min_area":
                continue
            parts = getattr(g, "geoms", [g])
            for part in parts:
                if TOL_M2 < part.area < c.value:
                    p = part.representative_point()
                    out.append(Finding(c.severity, "too_small", fid, f"{label(fid)}: a patch of {part.area:.1f} m² is below "
                                       f"the {c.value:g} m² minimum ({c.text or ''})".rstrip(" ()"), part.area, (p.x, p.y),
                                       "city_rule"))
    return out
