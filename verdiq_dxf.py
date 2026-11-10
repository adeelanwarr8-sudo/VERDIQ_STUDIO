"""Read a DXF plan and turn layers into Verdiq quantities.

Areas come from closed polylines (including arc segments), hatches (including arc edges and island holes)
and, on area layers, circles. Counts come from block inserts, points and circles (tree symbols).
Drawing units are read from $INSUNITS (mm, cm, m, inch, feet); unitless drawings are assumed to be metres.
Geometry outside the plot boundary (legends, neighbouring plots) is not counted.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from ezdxf import path as dxfpath
from ezdxf import recover
from shapely.affinity import scale
from shapely.geometry import Polygon
from shapely.ops import unary_union

from verdiq_schema import Rulebook


@dataclass
class LayerStats:
    layer: str
    area_m2: float = 0.0
    polygons: int = 0
    symbols: int = 0                # inserts, points, circles
    geoms: list = field(default_factory=list, repr=False)
    points: list = field(default_factory=list, repr=False)   # symbol insertion points (x, y) in metres
    circles: list = field(default_factory=list, repr=False)  # circles as polygons (count as area on area layers)
    circle_area_m2: float = 0.0


INSUNITS_TO_M = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0, 14: 0.1}
MIN_AREA_CIRCLE_R_M = 1.0   # smaller circles on area layers are markers, not surfaces
FLATTEN_M = 0.01   # max deviation when turning arcs into straight segments (1 cm)


def _poly_from_points(pts) -> Polygon | None:
    pts = [(float(p[0]), float(p[1])) for p in pts]
    if len(pts) < 3:
        return None
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly if poly.area > 0 else None


def drawing_units_to_m(doc) -> float:
    return INSUNITS_TO_M.get(int(doc.header.get("$INSUNITS", 0) or 0), 1.0)


def _flat(p, dist) -> Polygon | None:
    pts = [(v.x, v.y) for v in p.flattening(dist)]
    return _poly_from_points(pts)


def _hatch_polygon(e, dist):
    """All boundary paths of a hatch combined with the even-odd rule, so islands become holes."""
    region = None
    for p in dxfpath.from_hatch(e):
        poly = _flat(p, dist)
        if poly is None:
            continue
        region = poly if region is None else region.symmetric_difference(poly)
    return region


def read_layers(path: str | Path, units_to_m: float | None = None) -> dict[str, LayerStats]:
    try:
        doc = ezdxf.readfile(str(path))
    except ezdxf.DXFStructureError:
        doc, _ = recover.readfile(str(path))
    if units_to_m is None:
        units_to_m = drawing_units_to_m(doc)
    dist = FLATTEN_M / units_to_m
    msp = doc.modelspace()
    stats: dict[str, LayerStats] = defaultdict(lambda: LayerStats(""))
    for e in msp:
        layer = e.dxf.layer
        s = stats[layer]
        s.layer = layer
        t = e.dxftype()
        poly = None
        try:
            if t == "LWPOLYLINE" and e.closed:
                poly = _flat(dxfpath.make_path(e), dist)
            elif t == "POLYLINE" and e.is_closed and not (e.is_poly_face_mesh or e.is_polygon_mesh):
                poly = _flat(dxfpath.make_path(e), dist)
            elif t == "HATCH":
                poly = _hatch_polygon(e, dist)
            elif t == "CIRCLE":
                c = e.dxf.center
                s.symbols += 1
                s.points.append((float(c[0]) * units_to_m, float(c[1]) * units_to_m))
                circ = _flat(dxfpath.make_path(e), dist) if e.dxf.radius * units_to_m >= MIN_AREA_CIRCLE_R_M else None
                if circ is not None:
                    s.circles.append(circ)
                continue
            elif t in ("INSERT", "POINT"):
                loc = e.dxf.insert if t == "INSERT" else e.dxf.location
                s.symbols += 1
                s.points.append((float(loc[0]) * units_to_m, float(loc[1]) * units_to_m))
                continue
        except (ValueError, TypeError, ezdxf.DXFError):
            continue
        if poly is not None and not poly.is_empty:
            s.geoms.append(poly)
            s.polygons += 1
    for s in stats.values():
        if units_to_m != 1.0:
            s.geoms = [scale(g, units_to_m, units_to_m, origin=(0, 0)) for g in s.geoms]
            s.circles = [scale(g, units_to_m, units_to_m, origin=(0, 0)) for g in s.circles]
        if s.geoms:
            s.area_m2 = unary_union(s.geoms).area   # overlaps on one layer count once
        if s.circles:
            s.circle_area_m2 = unary_union(s.geoms + s.circles).area - s.area_m2
    return dict(stats)


def area_geoms(s: LayerStats, measure: str) -> list:
    """Geometry that counts as area for a factor: circles count as area only on area layers."""
    return s.geoms + s.circles if measure == "area" else s.geoms


def plot_geometry(rulebook: Rulebook, stats: dict[str, LayerStats], plot_layer: str | None = None):
    """Plot boundary from an explicit layer or the rulebook's boundary-layer pattern."""
    if plot_layer:
        geoms = stats[plot_layer].geoms if plot_layer in stats else []
    else:
        cad = rulebook.cad_layers
        pattern = cad.plot_boundary_layer_pattern if cad and cad.plot_boundary_layer_pattern else None
        rx = re.compile(pattern) if pattern else None
        geoms = [g for name, s in stats.items()
                 if (rx and rx.match(name)) or name.strip().upper() in PLOT_LAYER_NAMES for g in s.geoms]
    return unary_union(geoms) if geoms else None


# Verdiq's own layer standard (works for every rulebook): the plot boundary on one of these layers,
# and each surface or quality on a layer named exactly after its factor id, e.g. "bed_unbuilt", "tree_new_large".
PLOT_LAYER_NAMES = {"VERDIQ_PLOT", "PLOT", "TOMTGRANS", "TOMTGRÄNS", "FASTIGHETSGRANS", "FASTIGHETSGRÄNS"}


def auto_mapping(rulebook: Rulebook, layers: list[str]) -> dict[str, str]:
    """Map layers to factors: first the municipality's CAD layer standard, then Verdiq's own standard
    (layer named exactly after a factor id, case-insensitive)."""
    ids = {f.id.lower(): f.id for f in rulebook.factors}
    cad = rulebook.cad_layers
    rx = re.compile(cad.code_pattern) if cad else None
    out = {}
    for layer in layers:
        m = rx.match(layer.strip()) if rx else None
        if m and m.group(1) in cad.codes:
            out[layer] = cad.codes[m.group(1)]
        elif layer.strip().lower() in ids:
            out[layer] = ids[layer.strip().lower()]
    return out


def plot_area_from_layers(rulebook: Rulebook, stats: dict[str, LayerStats]) -> float | None:
    g = plot_geometry(rulebook, stats)
    return g.area if g is not None else None


def quantities(rulebook: Rulebook, stats: dict[str, LayerStats], mapping: dict[str, str],
               plot=None) -> dict[str, float]:
    """layer -> factor id mapping to factor quantities (m2 for area factors, symbol count for count factors).
    With `plot`, only what lies inside the plot is counted (legends and neighbouring plots are left out)."""
    from shapely.geometry import Point
    geoms: dict[str, list] = defaultdict(list)
    counts: dict[str, float] = defaultdict(float)
    for layer, fid in mapping.items():
        if not fid or layer not in stats:
            continue
        f = rulebook.factor(fid)
        s = stats[layer]
        if f.measure == "count":
            counts[fid] += sum(1 for x, y in s.points if plot is None or plot.covers(Point(x, y)))
        else:
            geoms[fid].extend(area_geoms(s, f.measure))
    q = dict(counts)
    for fid, gs in geoms.items():
        g = unary_union(gs)
        q[fid] = (g.intersection(plot) if plot is not None else g).area
    return {k: round(v, 2) for k, v in q.items() if v}
