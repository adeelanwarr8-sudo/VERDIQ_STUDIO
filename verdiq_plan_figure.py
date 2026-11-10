"""Draw an imported plan: surfaces coloured by type, elements as dots, findings as red markers."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

KIND_COLOURS = {"green": "#7fb77e", "roof": "#b9d7a8", "water": "#7fb3d5", "hard": "#c9c3b8", "sealed": "#9a948a",
                "quality": "#2f7d4f"}


def _kind(rb, fid):
    sp = rb.spatial
    f = rb.factor(fid)
    if sp and fid in sp.roof:
        return "roof"
    if f.kind == "supplementary":
        return "quality"
    if f.factor == 0:
        return "sealed"
    if "water" in fid or "pond" in fid:
        return "water"
    if "paving" in fid:
        return "hard"
    return "green"


def plan_figure(rb, stats, mapping, plot=None, findings=(), width_in: float = 7.5):
    fig, ax = plt.subplots(figsize=(width_in, width_in * 0.7), dpi=150)
    seen = set()
    order = sorted(mapping.items(), key=lambda kv: (rb.factor(kv[1]).kind == "supplementary", kv[0]))
    for layer, fid in order:
        if not fid or layer not in stats:
            continue
        k = _kind(rb, fid)
        for g in stats[layer].geoms:
            for poly in getattr(g, "geoms", [g]):
                x, y = poly.exterior.xy
                if k == "quality":
                    ax.plot(x, y, color=KIND_COLOURS[k], lw=1.2, ls="--")
                else:
                    ax.fill(x, y, color=KIND_COLOURS[k], alpha=0.85, lw=0.6, ec="white")
        for px, py in stats[layer].points:
            ax.plot(px, py, "o", ms=7 if "tree" in fid or "trad" in layer.lower() else 4, color="#1e5631", mec="white", mew=0.8)
        seen.add(k)
    if plot is not None:
        for poly in getattr(plot, "geoms", [plot]):
            x, y = poly.exterior.xy
            ax.plot(x, y, color="#1d2420", lw=1.6)
        _zoom(ax, plot)
    for i, f in enumerate(f for f in findings if f.location and f.severity in ("error", "warning")):
        ax.plot(*f.location, marker="X", ms=11, color="#c0392b" if f.severity == "error" else "#d68910", mec="white", mew=1)
        ax.annotate(str(i + 1), f.location, xytext=(6, 6), textcoords="offset points", fontsize=8, color="#1d2420",
                    weight="bold")
    names = {"green": "Planted ground", "roof": "Green roof", "water": "Water", "hard": "Permeable paving",
             "sealed": "Sealed", "quality": "Quality (dashed)"}
    ax.legend(handles=[Patch(color=KIND_COLOURS[k], label=names[k]) for k in names if k in seen],
              loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=6, frameon=False, fontsize=8)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout()
    return fig


def _zoom(ax, plot, pad_frac=0.04):
    """Frame the plot boundary (legends and neighbouring plots drawn outside it are cut away)."""
    x0, y0, x1, y1 = plot.bounds
    p = max(x1 - x0, y1 - y0) * pad_frac
    ax.set_xlim(x0 - p, x1 + p)
    ax.set_ylim(y0 - p, y1 + p)


# ---------------------------------------------------------------- improved design (indicative placement)
STEP_COLOURS = ["#e07a5f", "#f2cc8f", "#81b29a", "#9b5de5", "#f15bb5", "#00bbf9", "#fee440", "#00f5d4", "#ef476f",
                "#118ab2", "#06d6a0", "#ffd166", "#8338ec", "#3a86ff", "#fb5607", "#ff006e"]


def _carve(region, area):
    """Take about `area` m2 from `region`, largest parts first, as compact bands. Returns (taken, rest)."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    if region is None or region.is_empty or area <= 0:
        return None, region
    if area >= region.area * 0.995:
        return region, None
    parts = sorted(getattr(region, "geoms", [region]), key=lambda g: -g.area)
    taken, need = [], area
    for part in parts:
        if need <= 0.5:
            break
        if part.area <= need:
            taken.append(part)
            need -= part.area
            continue
        x0, y0, x1, y1 = part.bounds
        lo, hi = y0, y1
        for _ in range(40):
            mid = (lo + hi) / 2
            a = part.intersection(box(x0 - 1, y0 - 1, x1 + 1, mid)).area
            lo, hi = (mid, hi) if a < need else (lo, mid)
        taken.append(part.intersection(box(x0 - 1, y0 - 1, x1 + 1, hi)))
        need = 0
    t = unary_union(taken)
    return t, region.difference(t)


def _spread_points(region, n, avoid=()):
    """n well-spread points inside region (farthest-point sampling on a grid)."""
    import numpy as np
    from shapely.geometry import Point
    if region is None or region.is_empty or n <= 0:
        return []
    x0, y0, x1, y1 = region.bounds
    step = max(min(x1 - x0, y1 - y0) / 30, 0.5)
    inner = region.buffer(-1.0) if region.buffer(-1.0).area > 0 else region
    cand = [(x, y) for x in np.arange(x0, x1, step) for y in np.arange(y0, y1, step) if inner.contains(Point(x, y))]
    if not cand:
        return [(region.representative_point().x, region.representative_point().y)] * n
    cand = np.array(cand)
    chosen = list(avoid)
    out = []
    for _ in range(n):
        if chosen:
            d = np.min(np.hypot(cand[:, None, 0] - np.array(chosen)[None, :, 0],
                                cand[:, None, 1] - np.array(chosen)[None, :, 1]), axis=1)
            i = int(d.argmax())
        else:
            i = len(cand) // 2
        out.append(tuple(cand[i]))
        chosen.append(tuple(cand[i]))
    return out


def improved_plan_figure(rb, stats, mapping, plot, steps, width_in: float = 7.5, lang: str = "en",
                         legend_inside: bool = True):
    """The current plan with Verdiq's interventions placed indicatively: area qualities on existing planting,
    conversions on paving, roof items on roofs, new elements as markers. Placement is a sketch, not a design."""
    from matplotlib.lines import Line2D
    from shapely.ops import unary_union
    fig = plan_figure(rb, stats, mapping, plot, (), width_in)
    ax = fig.axes[0]
    by_factor: dict[str, list] = {}
    pts_existing = []
    for layer, fid in mapping.items():
        if fid and layer in stats:
            by_factor.setdefault(fid, []).extend(stats[layer].geoms)
            pts_existing += stats[layer].points
    clip = (lambda g: g.intersection(plot)) if plot is not None else (lambda g: g)
    geom = {k: clip(unary_union(v)) for k, v in by_factor.items() if v}
    planting_ids = [k for k in geom if _kind(rb, k) == "green"]
    roof_ids = [k for k in geom if _kind(rb, k) in ("roof", "sealed")]
    free = {"planting": unary_union([geom[k] for k in planting_ids]) if planting_ids else None,
            "roof": unary_union([geom[k] for k in roof_ids]) if roof_ids else None}
    req = rb.spatial.quality_requires if rb.spatial else {}
    handles, items = [], []
    marker_pts = list(pts_existing)
    for i, s in enumerate(steps):
        col = STEP_COLOURS[i % len(STEP_COLOURS)]
        fid, unit, qty = s["factor_id"], s["unit"], float(s["quantity"])
        label = s["label"]
        if unit == "st":
            host = free["planting"] if free["planting"] is not None else (plot if plot is not None else None)
            for (x, y) in _spread_points(host, int(qty), marker_pts):
                ax.plot(x, y, marker="*", ms=12, color=col, mec="#1d2420", mew=0.6, zorder=8)
                marker_pts.append((x, y))
            handles.append(Line2D([], [], marker="*", ls="", ms=10, color=col, mec="#1d2420", label=f"{label} ({int(qty)})"))
            items.append((col, "star", f"{label} ({int(qty)})"))
            continue
        if s.get("from_factor_id") and s["from_factor_id"] in geom:
            taken, geom[s["from_factor_id"]] = _carve(geom[s["from_factor_id"]], qty)
            hatch = "xx"
        else:
            hosts = req.get(fid)
            roofy = any(w in fid for w in ("roof", "terrace", "balcony", "tak"))
            if hosts:
                region = unary_union([geom[h] for h in hosts if h in geom]) if any(h in geom for h in hosts) else None
                key = None
            else:
                key = "roof" if roofy and free["roof"] is not None else "planting"
                region = free[key]
            if region is None:
                continue
            taken, rest = _carve(region, qty)
            if key:
                free[key] = rest if rest is not None and not rest.is_empty else region   # reuse when exhausted
            hatch = "//"
        if taken is None or taken.is_empty:
            continue
        for poly in getattr(taken, "geoms", [taken]):
            if poly.geom_type != "Polygon" or poly.area < 0.05:
                continue
            ax.fill(*poly.exterior.xy, fc=col, alpha=0.55, ec=col, lw=0.8, hatch=hatch, zorder=6)
        handles.append(Patch(fc=col, alpha=0.6, hatch=hatch, label=f"{label} ({qty:,.0f} m²)"))
        items.append((col, "area", f"{label} ({qty:,.0f} m²)"))
    if not legend_inside:
        fig.tight_layout()
        return fig, items
    old = ax.get_legend()
    if old:
        old.remove()
    if handles:
        ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2, frameon=False, fontsize=6.5)
    note = {"sv": "Indikativ placering av Verdiqs åtgärder: landskapsarkitekten bestämmer var.",
            "en": "Indicative placement of Verdiq's interventions: the landscape architect decides where."}[lang]
    ax.set_title(note, fontsize=7.5, color="#5b6b61", loc="left")
    fig.tight_layout()
    return fig
