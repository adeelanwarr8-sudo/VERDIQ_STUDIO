"""Verdiq Studio - green area factor design tool for architects, landscape architects and planners.

Run: streamlit run streamlit_app.py   (all Verdiq Studio files sit in this one folder)
"""
from __future__ import annotations

from pathlib import Path

import json  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import yaml  # noqa: E402

from verdiq_calculator import calculate  # noqa: E402
from verdiq_advice import suggest_package  # noqa: E402
from verdiq_spatial import check_plan  # noqa: E402
from verdiq_dxf import auto_mapping, plot_geometry, quantities, read_layers  # noqa: E402
from verdiq_ui import findings_list, get_template_map, save_upload, setup  # noqa: E402

CURRENT = "current"
T = {
    "en": {"scenario": "Scenario", "current": "Current design", "improved": "Verdiq improvement proposal",
           "improved_n": "Verdiq improvement proposal {n}", "variant": "Variant {n}",
           "revised": "Your improved design", "revised_n": "Your improved design {n}",
           "draft": "Your improved design (not saved)",
           "save": "Show Verdiq's improvement proposal", "save_yours": "Save your improved design results",
           "confirm": "Confirm and perform the analysis",
           "perform": "Perform the analysis", "duplicate": "Duplicate", "delete": "Delete"},
    "sv": {"scenario": "Scenario", "current": "Nuvarande förslag", "improved": "Verdiqs förbättringsförslag",
           "improved_n": "Verdiqs förbättringsförslag {n}", "variant": "Variant {n}",
           "revised": "Ditt förbättrade förslag", "revised_n": "Ditt förbättrade förslag {n}",
           "draft": "Ditt förbättrade förslag (ej sparat)",
           "save": "Visa Verdiqs förbättringsförslag", "save_yours": "Spara resultatet för ditt förbättrade förslag",
           "confirm": "Bekräfta och utför analysen",
           "perform": "Utför analysen", "duplicate": "Duplicera", "delete": "Ta bort"},
}

CSS = """
<style>
:root { --vq-green:#2f7d4f; --vq-green-soft:#e8f3ec; --vq-red:#b42318; --vq-red-soft:#fdecea; --vq-ink:#1d2420;
        --vq-muted:#5b6b61; --vq-line:#dfe6e1; --vq-amber:#b54708; }
.block-container { padding-top: 1.6rem; max-width: 1400px; }
.vq-hero { display:flex; align-items:center; gap:14px; padding:14px 18px; border-radius:14px;
           background:linear-gradient(120deg,#1f5c3a 0%,#2f7d4f 55%,#5fa87a 100%); color:white; margin-bottom:10px; }
.vq-hero h1 { font-size:1.45rem; margin:0; color:white; letter-spacing:.2px; }
.vq-hero p { margin:2px 0 0 0; opacity:.9; font-size:.92rem; }
.vq-logo { font-size:2rem; line-height:1; }
.vq-steps { display:flex; gap:8px; margin:6px 0 14px 0; flex-wrap:wrap; }
.vq-step { flex:1; min-width:150px; border:1px solid var(--vq-line); border-radius:10px; padding:8px 12px; background:white;
           font-size:.88rem; color:var(--vq-muted); }
.vq-step b { display:block; color:var(--vq-ink); font-size:.92rem; }
.vq-step.done { border-color:#9fd0b0; background:var(--vq-green-soft); }
.vq-step.now { border-color:var(--vq-green); box-shadow:0 0 0 2px rgba(47,125,79,.15); }
.vq-cards { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:6px 0 10px 0; }
.vq-card { border:1px solid var(--vq-line); border-radius:12px; padding:10px 14px; background:white; }
.vq-card .k { font-size:.78rem; color:var(--vq-muted); text-transform:uppercase; letter-spacing:.4px; }
.vq-card .v { font-size:1.7rem; font-weight:700; color:var(--vq-ink); line-height:1.25; }
.vq-card .s { font-size:.8rem; color:var(--vq-muted); }
.vq-card.pass .v { color:var(--vq-green); } .vq-card.fail .v { color:var(--vq-red); }
.vq-pill { display:inline-block; padding:4px 12px; border-radius:999px; font-weight:600; font-size:.88rem; }
.vq-pill.pass { background:var(--vq-green-soft); color:var(--vq-green); }
.vq-pill.fail { background:var(--vq-red-soft); color:var(--vq-red); }
.vq-pill.na { background:#fff4e5; color:var(--vq-amber); }
.vq-gauge { position:relative; height:12px; border-radius:6px; background:#eef2ef; margin:8px 0 4px 0; overflow:visible; }
.vq-gauge .fill { position:absolute; left:0; top:0; bottom:0; border-radius:6px; }
.vq-gauge .tick { position:absolute; top:-5px; bottom:-5px; width:2px; background:var(--vq-ink); }
.vq-bal { margin:4px 0; }
.vq-bal .row { display:grid; grid-template-columns: 150px 1fr 70px; gap:10px; align-items:center; font-size:.86rem; margin:5px 0; }
.vq-bal .bar { position:relative; height:10px; background:#eef2ef; border-radius:5px; }
.vq-bal .bar .fill { position:absolute; left:0; top:0; bottom:0; border-radius:5px; }
.vq-bal .bar .tick { position:absolute; top:-4px; bottom:-4px; width:2px; background:var(--vq-ink); }
.vq-delta { font-weight:700; } .vq-delta.up { color:var(--vq-green); } .vq-delta.down { color:var(--vq-red); }
.vq-colhead { font-weight:700; font-size:1.05rem; color:var(--vq-ink); margin:2px 0 6px 0; }
</style>
"""

ss = st.session_state
ss.setdefault("options", {CURRENT: {}})
ss.setdefault("meta", {CURRENT: {"kind": "current", "steps": [], "analysed": False, "edited": False}})
ss.setdefault("active", CURRENT)
ss.setdefault("plan", None)
ss.setdefault("plans", {})                  # scenario key -> its own imported drawing
if ss.plan is not None and CURRENT not in ss.plans:
    ss.plans[CURRENT] = ss.plan
for _k in ss.options:                       # scenarios set from outside (tests, project files) get default metadata
    ss.meta.setdefault(_k, {"kind": "current" if _k == CURRENT else "variant", "steps": [], "analysed": True,
                            "edited": False})


def _keep_valid(rb):
    valid = {f.id for f in rb.factors}
    ss.options = {k: {f: v for f, v in o.items() if f in valid} for k, o in ss.options.items()}
    ss.plan = None
    ss.plans = {}


ctx = setup("Verdiq Studio", "Design to the green area factor, city by city", on_rulebook_change=_keep_valid)
rb, sha, lang, entry, muni, calc_kw, lab = ctx.rb, ctx.sha, ctx.lang, ctx.entry, ctx.muni, ctx.calc_kw, ctx.lab
tr = dict(T["en"], **{k: v for k, v in T.get(lang, T["en"]).items()
                      if k in ("scenario", "current", "improved", "improved_n", "variant", "revised", "revised_n", "draft")})   # names follow the language
st.markdown(CSS, unsafe_allow_html=True)


def disp(key: str) -> str:
    m = ss.meta.get(key, {})
    if key == CURRENT:
        return tr["current"]
    if m.get("kind") == "improved":
        n = m.get("n", 1)
        return tr["improved"] if n == 1 else tr["improved_n"].format(n=n)
    if m.get("kind") == "variant":
        return tr["variant"].format(n=m.get("n", 1)) if m.get("n") else key
    if m.get("kind") == "revised":
        if not m.get("saved"):
            return tr["draft"]
        n = m.get("n", 1)
        return tr["revised"] if n == 1 else tr["revised_n"].format(n=n)
    return key


def plan_of(key):
    """The drawing a scenario is based on: its own (current, revised) or its parent's (improved, variant)."""
    seen = set()
    while key and key not in seen:
        if key in ss.plans:
            return ss.plans[key]
        seen.add(key)
        key = ss.meta.get(key, {}).get("parent")
    return None


def pa(key):
    return float(ss.meta.get(key, {}).get("plot_area") or ss.get("plot_area") or 0.0)


def run(key):
    return calculate(rb, ss.options[key], pa(key), rulebook_sha=sha, **calc_kw)


# ---------------------------------------------------------------- visual building blocks
def hero():
    st.markdown('<div class="vq-hero"><div class="vq-logo">🌿</div><div><h1>Verdiq Studio</h1>'
                f'<p>Green area factor for {rb.meta.municipality} · {rb.meta.scheme} {rb.meta.version}: import the plan, '
                'confirm the quantities, get the result and a package of improvements.</p></div></div>',
                unsafe_allow_html=True)


def stepper():
    m = ss.meta[CURRENT]
    has_plan, analysed = CURRENT in ss.plans, m["analysed"]
    has_improved = any(v.get("kind") == "improved" or (v.get("kind") == "revised" and v.get("saved"))
                       for v in ss.meta.values())
    steps = [("1 · Import plan", "DXF uploaded" if has_plan else "Upload a DXF", has_plan),
             ("2 · Confirm quantities", "Confirmed" if analysed else "Check what Verdiq detected", analysed),
             ("3 · Results and advice", "Result ready" if analysed else "After confirmation", analysed),
             ("4 · Compare", "Ready to compare" if has_improved else "Verdiq's proposal or your own improved design",
              has_improved)]
    now = next((i for i, s in enumerate(steps) if not s[2]), None)
    html = "".join(f'<div class="vq-step {"done" if done else ("now" if i == now else "")}"><b>{"✓ " if done else ""}{t}</b>{d}</div>'
                   for i, (t, d, done) in enumerate(steps))
    st.markdown(f'<div class="vq-steps">{html}</div>', unsafe_allow_html=True)


def status_pill(r):
    if r.passed is True:
        return '<span class="vq-pill pass">✓ Meets the requirement</span>'
    if r.passed is False:
        return '<span class="vq-pill fail">✗ Does not meet the requirement</span>'
    return '<span class="vq-pill na">Incomplete: see notes</span>'


def result_cards(r, compact=False, plot_area=None):
    cls = "pass" if r.passed_target else ("fail" if r.passed_target is False else "")
    gyf, sub = f"{r.score:.2f}", f"unrounded {r.score_unrounded:.3f}"
    if r.passed_target is False and r.target is not None and r.score >= r.target:
        gyf, sub = f"{r.score_unrounded:.3f}", f"rounds to {r.score:.2f} but is below the target"
    cards = [("Green area factor", gyf, sub, cls),
             ("Target", "–" if r.target is None else f"{r.target:.2f}", (r.target_source or "")[:40], ""),
             ("Eco-effective area", f"{r.total_points:,.0f} m²".replace(",", " "), f"plot {plot_area or 0:,.0f} m²".replace(",", " "), ""),
             ("Shortfall", f"{r.shortfall_points:,.0f} m²".replace(",", " ") if r.shortfall_points else "none",
              "eco-m² missing" if r.shortfall_points else "target reached", "fail" if r.shortfall_points else "pass")]
    if compact:
        cards = [cards[0], cards[2]]
        cols = "repeat(2,minmax(0,1fr))"
    else:
        cols = "repeat(4,minmax(0,1fr))"
    html = "".join(f'<div class="vq-card {c}"><div class="k">{k}</div><div class="v">{v}</div><div class="s">{s}</div></div>'
                   for k, v, s, c in cards)
    st.markdown(f'<div class="vq-cards" style="grid-template-columns:{cols}">{html}</div>', unsafe_allow_html=True)
    if r.target:
        top = max(r.target * 1.5, r.score * 1.1)
        col = "#2f7d4f" if r.passed_target else "#b42318"
        st.markdown(f'<div class="vq-gauge"><div class="fill" style="width:{min(100, 100 * r.score / top):.1f}%;'
                    f'background:{col}"></div><div class="tick" style="left:{100 * r.target / top:.1f}%"></div></div>'
                    f'<div style="font-size:.78rem;color:#5b6b61">Score {r.score_unrounded:.3f} against target {r.target:.2f} (black line)</div>',
                    unsafe_allow_html=True)
    st.markdown(status_pill(r), unsafe_allow_html=True)


def balancing_bars(r):
    if not r.balancing:
        return
    rows = []
    for g in r.balancing:
        need = g.min_share or 0
        col = "#2f7d4f" if g.passed else ("#b42318" if g.passed is False else "#b54708")
        rows.append(f'<div class="row"><div>{g.name}</div><div class="bar"><div class="fill" style="width:{min(100, 100 * g.share):.0f}%;'
                    f'background:{col}"></div><div class="tick" style="left:{100 * need:.0f}%"></div></div>'
                    f'<div style="text-align:right">{g.achieved}/{g.max} {"✓" if g.passed else "✗" if g.passed is False else ""}</div></div>')
    st.markdown(f'<div class="vq-bal">{"".join(rows)}</div>'
                '<div style="font-size:.78rem;color:#5b6b61">Bars: share of qualities present · black line: required share</div>',
                unsafe_allow_html=True)
    if any(g.indicative for g in r.balancing):
        st.caption("Indicative only: counted from factor groups. The city counts individual ecosystem services per "
                   "factor in its own template; check the balancing there before submitting.")


def plan_fig(key):
    """Draw a scenario's plan (with Verdiq's interventions placed indicatively) and list them as colour chips."""
    from verdiq_plan_figure import improved_plan_figure, plan_figure
    p = plan_of(key)
    if p is None:
        st.caption("No drawing imported: quantities only.")
        return
    steps = ss.meta.get(key, {}).get("steps") or []
    if not steps:
        st.pyplot(plan_figure(rb, p["stats"], p["mapping"], p["plot"], (), width_in=7.0), width="stretch")
        return
    fig, items = improved_plan_figure(rb, p["stats"], p["mapping"], p["plot"], steps, width_in=7.0, lang=lang,
                                      legend_inside=False)
    st.pyplot(fig, width="stretch")
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;margin:2px 8px 2px 0;font-size:.78rem">'
        f'<span style="width:12px;height:12px;border-radius:{"50%" if kind == "star" else "3px"};background:{c};'
        f'display:inline-block;border:1px solid #1d2420"></span>{lbl}</span>' for c, kind, lbl in items)
    with st.expander(f"Map key: {len(items)} interventions (round = elements, square = areas)"):
        st.markdown(chips, unsafe_allow_html=True)


# ================================================================ DESIGNER
def designer():
    with st.sidebar:
        st.divider()
        names = list(ss.options)
        ss.active = st.selectbox(tr["scenario"], names, index=names.index(ss.active) if ss.active in names else 0,
                                 format_func=disp)
        for k, v in ss.pop("_pa_set", {}).items():     # plot areas set by an import, applied before the widget exists
            ss[f"pa_{k}"] = v
        wkey = f"pa_{ss.active}"
        if wkey not in ss:
            ss[wkey] = pa(ss.active) or 2000.0
        ss.meta[ss.active]["plot_area"] = st.number_input("Plot area (m²)", min_value=0.0, step=10.0, key=wkey)
        if ss.active == CURRENT:
            ss.plot_area = ss.meta[CURRENT]["plot_area"]
        c1, c2 = st.columns(2)
        if c1.button(tr["duplicate"], width="stretch"):
            n = 1 + sum(1 for v in ss.meta.values() if v.get("kind") == "variant")
            new = f"variant-{n}"
            ss.options[new] = dict(ss.options[ss.active])
            ss.meta[new] = {"kind": "variant", "n": n, "steps": list(ss.meta[ss.active].get("steps", [])),
                            "analysed": ss.meta[ss.active]["analysed"], "edited": False, "parent": ss.active,
                            "plot_area": pa(ss.active)}
            ss.active = new
            st.rerun()
        if c2.button(tr["delete"], width="stretch", disabled=ss.active == CURRENT):
            ss.options.pop(ss.active)
            ss.meta.pop(ss.active, None)
            ss.active = CURRENT
            st.rerun()

    hero()
    stepper()
    inputs = ss.options[ss.active]
    meta = ss.meta[ss.active]
    tab_plan, tab_qty, tab_res, tab_cmp = st.tabs(["1 · Import plan", "2 · Quantities", "3 · Results and advice",
                                                    "4 · Compare designs"])

    # ------------------------------------------------------------ 1 import + confirmation
    with tab_plan:
        st.write("Upload a DXF exported from AutoCAD, Rhino, Revit or Vectorworks. Closed polylines (including curves) and "
                 "hatches (including holes) give areas; blocks, points and circles count as elements (trees, nest boxes). "
                 "Units are read from the drawing (mm or m). Only what lies inside the plot boundary is counted, "
                 "so legends and neighbouring plots are left out.")
        if rb.cad_layers:
            st.caption(f"{rb.meta.municipality} has a CAD layer standard ({rb.cad_layers.standard}); matching layers map automatically.")
        up = st.file_uploader("DXF plan", type=["dxf"])
        if up:
            stats = read_layers(save_upload(up, ".dxf"))
            auto = auto_mapping(rb, list(stats))
            with st.expander("Layer mapping: change a factor here if Verdiq mapped a layer wrongly", expanded=False):
                df = pd.DataFrame([{"Layer": n, "Area (m²)": round(s.area_m2, 1), "Elements": s.symbols, "Factor": auto.get(n, "")}
                                   for n, s in sorted(stats.items())])
                edited = st.data_editor(df, hide_index=True, width="stretch", disabled=["Layer", "Area (m²)", "Elements"],
                                        column_config={"Factor": st.column_config.SelectboxColumn(
                                            "Factor", options=[""] + [f.id for f in rb.factors],
                                            help="Leave empty to ignore the layer")})
            mapping = {r.Layer: r.Factor for r in edited.itertuples() if r.Factor}
            plot = plot_geometry(rb, stats)
            q = quantities(rb, stats, mapping, plot=plot)
            findings = check_plan(rb, stats, mapping, plot)
            problems = [f for f in findings if f.severity in ("error", "warning")]
            c1, c2 = st.columns([3, 2])
            with c1:
                from verdiq_plan_figure import plan_figure
                st.pyplot(plan_figure(rb, stats, mapping, plot, findings), width="stretch")
            with c2:
                with st.container(border=True):
                    st.markdown("#### Verdiq has detected these quantities")
                    st.write("Please check that they are correct before continuing. Nothing is calculated until you confirm.")
                    st.markdown(f"- **Plot area:** {plot.area:,.1f} m² (from the plot boundary layer)".replace(",", " ")
                                if plot is not None else "- **Plot area:** no boundary layer found: enter it in the sidebar")
                    n_trees = sum(v for k, v in q.items() if rb.factor(k).measure == "count" and rb.factor(k).kind == "base")
                    st.markdown(f"- **{len(mapping)} of {len(stats)} layers** mapped to **{len(q)} factors** · "
                                f"{int(n_trees)} trees and other elements")
                    if problems:
                        st.markdown(f'<span class="vq-pill fail">{len(problems)} drawing problem(s): review before confirming</span>',
                                    unsafe_allow_html=True)
                        findings_list(findings)
                    else:
                        st.markdown('<span class="vq-pill pass">No drawing problems found</span>', unsafe_allow_html=True)
                    qdf = pd.DataFrame([{"Factor": lab(k), "Quantity": f"{v:,.1f} m²".replace(",", " ")
                                         if rb.factor(k).measure != "count" else f"{int(v)} st"} for k, v in q.items()])
                    st.dataframe(qdf, hide_index=True, width="stretch", height=min(38 * (len(qdf) + 1), 360))
                    mode = "replace"
                    if ss.meta[CURRENT]["analysed"] and CURRENT in ss.plans:
                        mode = st.radio("What is this drawing?", ["revised", "replace"], format_func={
                            "revised": "Your improved design: keep the current design and evaluate this one",
                            "replace": "A replacement for the current design: start over"}.get)
                    if st.button(tr["confirm"], type="primary", width="stretch", disabled=not q):
                        plan = {"stats": stats, "mapping": mapping, "plot": plot}
                        area = round(plot.area, 1) if plot is not None else pa(CURRENT)
                        if mode == "revised":
                            draft = next((k for k, v in ss.meta.items() if v.get("kind") == "revised" and not v.get("saved")),
                                         None)   # a new upload replaces an unsaved one
                            n = 1 + sum(1 for v in ss.meta.values() if v.get("kind") == "revised" and v.get("saved"))
                            key = draft or f"revised-{n}"
                            ss.options[key] = q
                            ss.meta[key] = {"kind": "revised", "n": n, "steps": [], "analysed": True, "edited": False,
                                            "plot_area": area, "saved": False}
                            ss.plans[key] = plan
                            ss["_pa_set"] = {key: area}
                            ss.active = key
                            ss.flash = ("Analysis done for your improved design. Check the result in **3 · Results and advice** "
                                        f"and click **{tr['save_yours']}** to compare it with the current design.")
                        else:
                            stale = [k for k in ss.meta if k != CURRENT]
                            for k in stale:
                                ss.options.pop(k, None)
                                ss.meta.pop(k, None)
                                ss.pop(f"pa_{k}", None)
                            ss.options[CURRENT] = q
                            ss.meta[CURRENT] = {"kind": "current", "steps": [], "analysed": True, "edited": False,
                                                "plot_area": area}
                            ss.plans = {CURRENT: plan}
                            ss.plan = plan
                            ss["_pa_set"] = {CURRENT: area}
                            ss.plot_area = area
                            ss.active = CURRENT
                            ss.flash = ("Analysis done. Open **3 · Results and advice**." +
                                        (f" {len(stale)} earlier scenario(s) based on the previous drawing were removed."
                                         if stale else ""))
                        st.rerun()
        if ss.get("flash"):
            st.success(ss.pop("flash"))

    # ------------------------------------------------------------ 2 quantities
    with tab_qty:
        st.caption(f"Quantities for **{disp(ss.active)}**. Edits here update the analysis directly once it has been performed.")
        df = pd.DataFrame([{"id": f.id, "Section": f.section, "Factor": f.label.text(lang),
                            "Unit": "count" if f.measure == "count" else "m²", "Weight": f.factor,
                            "Quantity": float(inputs.get(f.id, 0) or 0)} for f in rb.factors])
        edited_q = st.data_editor(df, hide_index=True, width="stretch", height=620,
                                  column_order=["Section", "Factor", "Unit", "Weight", "Quantity"],
                                  disabled=["Section", "Factor", "Unit", "Weight"],
                                  column_config={"Quantity": st.column_config.NumberColumn(min_value=0.0, step=1.0)})
        new = {r.id: r.Quantity for r in edited_q.itertuples() if r.Quantity}
        if new != inputs:
            ss.options[ss.active] = new
            inputs = new
            if meta["analysed"]:
                meta["edited"] = True

    # ------------------------------------------------------------ 3 results and advice
    with tab_res:
        if not pa(ss.active):
            st.info("Enter the plot area in the sidebar.")
            return
        if not meta["analysed"]:
            st.info("No analysis yet. Upload a plan in **1 · Import plan** and confirm the detected quantities, "
                    "or enter quantities by hand in **2 · Quantities** and perform the analysis here.")
            if inputs and st.button(tr["perform"], type="primary"):
                meta["analysed"] = True
                st.rerun()
        else:
            r = run(ss.active)
            st.markdown(f"### {disp(ss.active)}")
            if meta.get("edited"):
                st.caption("Quantities were edited manually after the analysis was performed.")
            result_cards(r, plot_area=pa(ss.active))

            left, right = st.columns([1, 1])
            with left:
                st.subheader("Balancing of ecosystem services")
                if r.balancing:
                    balancing_bars(r)
                else:
                    st.caption("This rulebook has no balancing requirement.")
            with right:
                if plan_of(ss.active) is not None:
                    st.subheader("Plan")
                    plan_fig(ss.active)

            if meta.get("kind") == "revised":
                with st.container(border=True):
                    st.subheader("Your improved design")
                    base = run(CURRENT) if ss.meta[CURRENT]["analysed"] else None
                    if base is not None:
                        d, dp = r.score_unrounded - base.score_unrounded, r.total_points - base.total_points
                        st.markdown(f'<span class="vq-delta {"up" if d >= 0 else "down"}">{d:+.2f} GYF · {dp:+,.0f} eco-m²</span>'
                                    f' compared with {disp(CURRENT)}'.replace(",", " "), unsafe_allow_html=True)
                    if meta.get("saved"):
                        st.success("Saved. It is shown next to the current design in **4 · Compare designs**, in place of "
                                   "Verdiq's proposal.")
                    else:
                        st.write("Save the result to compare your design with the current design. In **4 · Compare designs** "
                                 "it replaces Verdiq's improvement proposal.")
                        if st.button(tr["save_yours"], type="primary"):
                            meta["saved"] = True
                            ss.flash_res = (f"Saved as **{disp(ss.active)}**. Open **4 · Compare designs** to see it next to the "
                                            "current design.")
                            st.rerun()
            elif r.passed is False and r.target is not None:
                with st.container(border=True):
                    st.subheader("How to close the gap")
                    pkg = suggest_package(rb, inputs, pa(ss.active), calc_kw, lang=lang)
                    if pkg.steps:
                        st.markdown(f"**{len(pkg.steps)} design changes** take this design from **{r.score:.2f}** to "
                                    f"**{pkg.result.score:.2f}**" + (" and meet all balancing groups." if pkg.closes_balancing else "."))
                        st.dataframe(pd.DataFrame([{"Change": s.text, "Adds groups": " ".join(s.adds_groups),
                                                    "Eco-effective m²": round(s.points, 1)} for s in pkg.steps]),
                                     hide_index=True, width="stretch")
                        st.caption("Order: qualities on existing planting first, then elements such as trees, then converting "
                                   "surfaces. The predicted result is calculated with the same engine.")
                        if st.button(tr["save"], type="primary"):
                            n = 1 + sum(1 for v in ss.meta.values() if v.get("kind") == "improved")
                            new = f"improved-{n}"
                            ss.options[new] = {k: round(v, 1) for k, v in pkg.inputs.items()}
                            ss.meta[new] = {"kind": "improved", "n": n, "parent": ss.active, "analysed": True, "edited": False,
                                            "plot_area": pa(ss.active),
                                            "steps": list(meta.get("steps", [])) + [
                                                {"factor_id": s.factor_id, "label": s.label, "quantity": s.quantity,
                                                 "unit": s.unit, "from_factor_id": s.from_factor_id, "text": s.text}
                                                for s in pkg.steps]}
                            ss.active = new
                            ss.flash_res = (f"**{disp(new)}** created. Open **4 · Compare designs** to see it next to the "
                                            "current design.")
                            st.rerun()
                    if pkg.remaining_note:
                        st.info(pkg.remaining_note)
            if ss.get("flash_res"):
                st.success(ss.pop("flash_res"))

            with st.expander("Line items and notes", expanded=False):
                li = pd.DataFrame([{"Factor": i.label, "Input": i.input_value, "Area m²": i.quantity_m2, "Weight": i.factor,
                                    "Points": round(i.points, 2), "Groups": " ".join(i.groups)} for i in r.line_items])
                st.dataframe(li, hide_index=True, width="stretch")
                for m in r.messages:
                    (st.error if m.severity == "error" else st.warning if m.severity == "warning" else st.info)(
                        (f"**{lab(m.factor_id)}** - " if m.factor_id else "") + m.text)

            st.subheader("Report and export")
            with st.container(border=True):
                st.caption("A report to attach to the GYF submission: result, balancing, plan with drawing checks, "
                           "every line item, notes and a comparison of all scenarios.")
                p1, p2, p3 = st.columns(3)
                proj_name = p1.text_input("Project", ss.get("proj_name", ""), key="proj_name")
                proj_prop = p2.text_input("Property / address", ss.get("proj_prop", ""), key="proj_prop")
                proj_author = p3.text_input("Prepared by", ss.get("proj_author", ""), key="proj_author")
                if st.button("Create PDF report", type="primary"):
                    from verdiq_pdf import build_report, plan_png_bytes
                    with st.spinner("Building the report..."):
                        plan, plan_png, findings = plan_of(ss.active), None, []
                        if plan:
                            findings = check_plan(rb, plan["stats"], plan["mapping"], plan["plot"])
                            plan_png = plan_png_bytes(rb, plan, findings)
                        analysed = {k: o for k, o in ss.options.items() if ss.meta.get(k, {}).get("analysed")}
                        opts = {disp(k): run(k) for k in analysed} if len(analysed) > 1 else None
                        ss.pdf = build_report(r, rb, project={"name": proj_name, "property": proj_prop, "author": proj_author,
                                                              "option": disp(ss.active)}, plan_png=plan_png, findings=findings,
                                              options=opts, lang=lang)
                        clean = lambda s: re.sub(r"[^A-Za-z0-9ÅÄÖåäö_-]+", "_", s).strip("_")  # noqa: E731
                        ss.pdf_name = f"GYF_{clean(proj_name or muni)}_{clean(disp(ss.active))}.pdf"
                if ss.get("pdf"):
                    st.download_button("Download PDF report", ss.pdf, ss.pdf_name, "application/pdf")
                d1, d2, d3 = st.columns(3)
                d1.download_button("Line items (CSV)", li.to_csv(index=False).encode("utf-8"), "verdiq_line_items.csv", "text/csv")
                d2.download_button("Result (JSON)", json.dumps(r.to_dict(), ensure_ascii=False, indent=2, default=str),
                                   "verdiq_result.json", "application/json")
                d3.download_button("Project file", yaml.safe_dump({"rulebook": rb.key, "rulebook_sha": sha, "plot_area_m2": pa(ss.active),
                                                                   "scenarios": {disp(k): o for k, o in ss.options.items()}},
                                                                  allow_unicode=True),
                                   "project.verdiq.yaml", "text/yaml")
                tmap = get_template_map(entry.path)
                if tmap:
                    st.markdown("**Fill the city's own Excel template.** Upload the municipality's template; Verdiq writes the "
                                "quantities and the city's formulas do the rest.")
                    tpl = st.file_uploader("City template (.xlsx)", type=["xlsx"], key="tpl")
                    if tpl:
                        from verdiq_excel import fill_template
                        with tempfile.TemporaryDirectory() as td:
                            src_p, out_p = Path(td) / "t.xlsx", Path(td) / "filled.xlsx"
                            src_p.write_bytes(tpl.getvalue())
                            fill_template(src_p, tmap, inputs, pa(ss.active), out_p, built_share_pct=calc_kw["built_share_pct"])
                            st.download_button("Download filled template", out_p.read_bytes(),
                                               f"GYF_{muni}_{re.sub(r'[^A-Za-z0-9]+', '_', disp(ss.active))}.xlsx")

    # ------------------------------------------------------------ 4 compare designs
    with tab_cmp:
        analysed = [k for k in ss.options if ss.meta.get(k, {}).get("analysed")]
        kind = lambda k: ss.meta[k].get("kind")  # noqa: E731
        yours = [k for k in analysed if kind(k) == "revised" and ss.meta[k].get("saved")]
        proposals = [k for k in analysed if kind(k) == "improved"]
        variants = [k for k in analysed if kind(k) == "variant"]
        base = [CURRENT] if CURRENT in analysed else []
        if yours:        # the user's own saved design replaces Verdiq's proposal in the comparison
            pool, default = base + yours + variants, base + yours[-1:]
            st.caption("Your improved design has replaced Verdiq's proposal here. The proposal is still in the sidebar "
                       f"under **{tr['scenario']}**.")
        elif proposals:
            pool, default = base + proposals + variants, base + proposals[-1:]
        else:
            pool, default = base + variants, base + variants[-1:]
        if len(pool) < 2:
            st.info(f"Compare shows the current design next to Verdiq's improvement proposal (**{tr['save']}** in "
                    "**3 · Results and advice**), or next to your own improved design once you have uploaded it and "
                    f"clicked **{tr['save_yours']}**.")
            return
        chosen = st.multiselect("Scenarios side by side (up to 3)", pool, default=default, format_func=disp,
                                max_selections=3, key="cmp_" + "_".join(pool))
        if not chosen:
            return
        results = {k: run(k) for k in chosen}
        base = results.get(CURRENT) or results[chosen[0]]
        cols = st.columns(len(chosen))
        for col, k in zip(cols, chosen):
            r = results[k]
            with col:
                st.markdown(f'<div class="vq-colhead">{disp(k)}</div>', unsafe_allow_html=True)
                plan_fig(k)
        cols = st.columns(len(chosen))
        for col, k in zip(cols, chosen):
            r = results[k]
            with col:
                result_cards(r, compact=True, plot_area=pa(k))
                if r is not base:
                    d, dp = r.score - base.score, r.total_points - base.total_points
                    cls = "up" if d >= 0 else "down"
                    st.markdown(f'<span class="vq-delta {cls}">{d:+.2f} GYF · {dp:+,.0f} eco-m²</span> compared with '
                                f'{disp(CURRENT if CURRENT in results else chosen[0])}'.replace(",", " "), unsafe_allow_html=True)
                st.markdown("**Balancing**")
                balancing_bars(r)
                steps = ss.meta.get(k, {}).get("steps") or []
                if steps:
                    with st.expander(f"{len(steps)} interventions as a list"):
                        st.markdown("\n".join(f"- {s['text']}" for s in steps))


designer()
st.caption("Verdiq Studio is a calculation aid. The responsible landscape architect verifies inputs and results before submission.")
