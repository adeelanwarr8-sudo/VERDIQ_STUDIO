"""PDF report for Verdiq Studio: the document a landscape architect attaches to a GYF submission.

Contents: project and rulebook, result against target, balancing, plan drawing with numbered findings,
line items, notes, design-option comparison, and a statement of what the report is.
Uses the DejaVu Sans font bundled with matplotlib so Swedish characters, m² and ≥ print correctly.
"""
from __future__ import annotations

import io
import os
from datetime import date

import matplotlib
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

GREEN = colors.HexColor("#2f7d4f")
INK = colors.HexColor("#1d2420")
QUIET = colors.HexColor("#5b665f")
RULE = colors.HexColor("#d9e0dc")
TINT = colors.HexColor("#f2f6f3")
OK, BAD, WARN = colors.HexColor("#1f7a46"), colors.HexColor("#a32020"), colors.HexColor("#9a6b00")

T = {
    "en": {"title": "Green area factor report", "project": "Project", "property": "Property / address",
           "author": "Prepared by", "date": "Date", "rulebook": "Rules applied", "status": "Rulebook status",
           "result": "Result", "score": "Green area factor", "target": "Target", "eco": "Eco-effective area",
           "plot": "Plot area", "short": "Shortfall", "none": "none", "passes": "Meets the requirement",
           "fails": "Does not meet the requirement", "incomplete": "Incomplete - see notes",
           "balancing": "Balancing of ecosystem services", "group": "Group", "achieved": "Achieved",
           "possible": "Possible", "share": "Share", "required": "Required", "ok": "OK", "yes": "yes", "no": "no",
           "not_required": "Reported only - this scheme sets no minimum.",
           "indicative": "Indicative: the city counts individual ecosystem services per factor in its own template.",
           "plan": "Plan", "checks": "Drawing checks", "items": "Calculation", "factor_col": "Surface / quality",
           "input": "Input", "area": "Area m²", "weight": "Factor", "points": "Eco-effective m²", "groups": "Groups",
           "total": "Total", "notes": "Notes", "options": "Design options compared", "option": "Option",
           "verified": "verified against the municipality's own calculations",
           "draft": "draft - score verified, some rules still open", "page": "Page",
           "disclaimer": ("Calculated with Verdiq Studio under the rulebook named above. Verdiq is a calculation aid: "
                          "the responsible landscape architect verifies the inputs and results before submission. "
                          "Rulebook fingerprint {sha} identifies the exact rules used.")},
    "sv": {"title": "Grönytefaktor - beräkningsrapport", "project": "Projekt", "property": "Fastighet / adress",
           "author": "Upprättad av", "date": "Datum", "rulebook": "Tillämpade regler", "status": "Regelboksstatus",
           "result": "Resultat", "score": "Grönytefaktor", "target": "Krav", "eco": "Ekoeffektiv yta",
           "plot": "Tomtarea", "short": "Underskott", "none": "inget", "passes": "Uppfyller kravet",
           "fails": "Uppfyller inte kravet", "incomplete": "Ofullständig - se noteringar",
           "balancing": "Balansering av ekosystemtjänster", "group": "Grupp", "achieved": "Uppnått",
           "possible": "Möjligt", "share": "Andel", "required": "Krav", "ok": "OK", "yes": "ja", "no": "nej",
           "not_required": "Redovisas endast - modellen har inget minimikrav.",
           "indicative": "Indikativ: kommunen räknar enskilda ekosystemtjänster per faktor i sin egen mall.",
           "plan": "Situationsplan", "checks": "Kontroll av ritningen", "items": "Beräkning",
           "factor_col": "Yta / kvalitet", "input": "Indata", "area": "Area m²", "weight": "Faktor",
           "points": "Ekoeffektiv m²", "groups": "Grupper", "total": "Summa", "notes": "Noteringar",
           "options": "Jämförelse av alternativ", "option": "Alternativ",
           "verified": "verifierad mot kommunens egna beräkningar",
           "draft": "utkast - poäng verifierad, vissa regler öppna", "page": "Sida",
           "disclaimer": ("Beräknad med Verdiq Studio enligt regelboken ovan. Verdiq är ett beräkningsstöd: ansvarig "
                          "landskapsarkitekt kontrollerar indata och resultat före inlämning. Regelbokens "
                          "fingeravtryck {sha} identifierar exakt vilka regler som använts.")},
}


def _fonts():
    if "Verdiq" in pdfmetrics.getRegisteredFontNames():
        return
    d = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    pdfmetrics.registerFont(TTFont("Verdiq", os.path.join(d, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("Verdiq-Bold", os.path.join(d, "DejaVuSans-Bold.ttf")))


def _styles():
    def s(name, **kw):
        base = {"fontName": "Verdiq", "textColor": INK, "alignment": TA_LEFT}
        base.update(kw)
        return ParagraphStyle(name, **base)
    return {
        "brand": s("brand", fontName="Verdiq-Bold", fontSize=9, textColor=GREEN, leading=11),
        "h1": s("h1", fontName="Verdiq-Bold", fontSize=18, leading=22, spaceAfter=2),
        "sub": s("sub", fontSize=9.5, textColor=QUIET, leading=13),
        "h2": s("h2", fontName="Verdiq-Bold", fontSize=11.5, leading=15, spaceBefore=12, spaceAfter=5, textColor=GREEN),
        "body": s("body", fontSize=9, leading=12.5),
        "small": s("small", fontSize=7.8, leading=10.5, textColor=QUIET),
        "cell": s("cell", fontSize=8, leading=10),
        "cellb": s("cellb", fontName="Verdiq-Bold", fontSize=8, leading=10),
        "kpi_l": s("kpi_l", fontSize=7.8, textColor=QUIET, leading=10),
        "kpi_v": s("kpi_v", fontName="Verdiq-Bold", fontSize=17, leading=20),
        "verdict": s("verdict", fontName="Verdiq-Bold", fontSize=11, leading=14),
    }


def _table(rows, widths, header=True, num_cols=(), total_row=False):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [("FONTNAME", (0, 0), (-1, -1), "Verdiq"), ("FONTSIZE", (0, 0), (-1, -1), 8),
          ("TEXTCOLOR", (0, 0), (-1, -1), INK), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE), ("TOPPADDING", (0, 0), (-1, -1), 3),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), TINT), ("FONTNAME", (0, 0), (-1, 0), "Verdiq-Bold"),
               ("TEXTCOLOR", (0, 0), (-1, 0), QUIET)]
    for c in num_cols:
        st.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if total_row:
        st += [("FONTNAME", (0, -1), (-1, -1), "Verdiq-Bold"), ("LINEABOVE", (0, -1), (-1, -1), 0.8, INK)]
    t.setStyle(TableStyle(st))
    return t


def _num(x, d=1):
    s = f"{x:,.{d}f}".replace(",", " ")
    return s


def build_report(result, rulebook, *, project: dict | None = None, plan_png: bytes | None = None,
                 findings=(), options: dict | None = None, lang: str = "en") -> bytes:
    """Return the PDF as bytes. `options` maps option name -> Result for the comparison table."""
    _fonts()
    L = T.get(lang, T["en"])
    S = _styles()
    project = project or {}
    r, rb = result, rulebook
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=18 * mm, title=f"{L['title']} - {project.get('name') or rb.meta.municipality}",
                            author=project.get("author") or "Verdiq Studio", subject="GYF")
    W = A4[0] - 36 * mm
    P = lambda text, style="body": Paragraph(text, S[style])  # noqa: E731
    story = []

    # ---- header
    story += [P("VERDIQ STUDIO", "brand"), P(L["title"], "h1"),
              P(f"{rb.meta.name.text(lang)} · {rb.meta.municipality} · {rb.meta.version}", "sub"), Spacer(1, 8)]
    status = L["verified"] if rb.meta.status == "verified" else L["draft"] if rb.meta.status == "draft" else rb.meta.status
    meta = [[P(L["project"], "kpi_l"), P(project.get("name") or "-", "cellb"), P(L["date"], "kpi_l"),
             P(project.get("date") or date.today().isoformat(), "cell")],
            [P(L["property"], "kpi_l"), P(project.get("property") or "-", "cell"), P(L["author"], "kpi_l"),
             P(project.get("author") or "-", "cell")],
            [P(L["rulebook"], "kpi_l"), P(f"{rb.meta.id} @ {rb.meta.version}", "cell"), P(L["status"], "kpi_l"),
             P(status, "cell")]]
    if project.get("option"):
        meta.append([P(L["option"], "kpi_l"), P(project["option"], "cell"), P("", "cell"), P("", "cell")])
    mt = Table(meta, colWidths=[30 * mm, W / 2 - 30 * mm, 26 * mm, W / 2 - 26 * mm])
    mt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                            ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(mt)

    # ---- result
    story.append(P(L["result"], "h2"))
    kpis = [(L["score"], f"{r.score:.2f}"), (L["target"], "-" if r.target is None else f"{r.target:.2f}"),
            (L["eco"], f"{_num(r.total_points, 0)} m²"), (L["plot"], f"{_num(r.plot_area_m2, 0)} m²"),
            (L["short"], f"{_num(r.shortfall_points, 0)} m²" if r.shortfall_points else L["none"])]
    kt = Table([[P(k, "kpi_l") for k, _ in kpis], [P(v, "kpi_v") for _, v in kpis]], colWidths=[W / 5] * 5)
    kt.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    verdict, colour = {True: (L["passes"], OK), False: (L["fails"], BAD), None: (L["incomplete"], WARN)}[r.passed]
    vt = Table([[Paragraph(verdict, ParagraphStyle("v", parent=S["verdict"], textColor=colour))]], colWidths=[W])
    vt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TINT), ("LINEBEFORE", (0, 0), (0, -1), 3, colour),
                            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    story += [kt, Spacer(1, 6), vt]

    # ---- balancing
    if r.balancing:
        yn = {True: L["yes"], False: L["no"], None: "-"}
        rows = [[L["group"], L["achieved"], L["possible"], L["share"], L["required"], L["ok"]]]
        for g in r.balancing:
            rows.append([P(g.name, "cell"), str(g.achieved), str(g.max), f"{g.share:.0%}",
                         "-" if g.min_share is None else f"{g.min_share:.0%}", yn[g.passed]])
        block = [P(L["balancing"], "h2"), _table(rows, [W - 5 * 22 * mm] + [22 * mm] * 5, num_cols=(1, 2, 3, 4))]
        if not rb.balancing.required:
            block.append(P(L["not_required"], "small"))
        elif any(g.indicative for g in r.balancing):
            block.append(P(L["indicative"], "small"))
        story.append(KeepTogether(block))

    # ---- plan + drawing checks
    if plan_png:
        img = Image(io.BytesIO(plan_png))
        ratio = img.imageHeight / float(img.imageWidth)
        img.drawWidth, img.drawHeight = W, W * ratio
        if img.drawHeight > 125 * mm:
            img.drawHeight, img.drawWidth = 125 * mm, 125 * mm / ratio
        story += [KeepTogether([P(L["plan"], "h2"), img])]
    if findings:
        located = [f for f in findings if f.location and f.severity in ("error", "warning")]
        mark = {"error": "●", "warning": "●", "info": "○"}
        col = {"error": "#a32020", "warning": "#b8730a", "info": "#5b665f"}
        lines = [P(L["checks"], "h2")]
        for f in findings:
            n = f"[{located.index(f) + 1}] " if f in located else ""
            lines.append(P(f"<font color='{col[f.severity]}'>{mark[f.severity]}</font> {n}{f.text}", "body"))
        story += lines

    # ---- line items
    story.append(PageBreak())
    story.append(P(L["items"], "h2"))
    rows = [[L["factor_col"], L["input"], L["area"], L["weight"], L["points"], L["groups"]]]
    for i in r.line_items:
        unit = "" if i.unit_area_m2 is None else " st"
        rows.append([P(i.label, "cell"), f"{_num(i.input_value, 1 if unit == '' else 0)}{unit}", _num(i.quantity_m2),
                     f"{i.factor:g}", _num(i.points), " ".join(i.groups)])
    rows.append([L["total"], "", "", "", _num(r.total_points), ""])
    story.append(_table(rows, [W - 98 * mm, 20 * mm, 20 * mm, 14 * mm, 26 * mm, 18 * mm], num_cols=(1, 2, 3, 4),
                        total_row=True))
    story.append(P(f"{L['score']} = {_num(r.total_points)} / {_num(r.plot_area_m2)} = {r.score_unrounded:.3f} ≈ {r.score:.2f}",
                   "small"))

    # ---- notes
    notes = [m for m in r.messages if m.severity in ("warning", "error") or "template" in m.text]
    if notes:
        story.append(P(L["notes"], "h2"))
        for m in notes:
            label = rb.factor(m.factor_id).label.text(lang) + ": " if m.factor_id else ""
            story.append(P(f"• {label}{m.text}", "body"))

    # ---- options
    if options and len(options) > 1:
        rows = [[L["option"], L["score"], L["target"], L["eco"], L["short"], L["ok"]]]
        yn = {True: L["yes"], False: L["no"], None: "-"}
        for name, o in options.items():
            rows.append([P(name, "cell"), f"{o.score:.2f}", "-" if o.target is None else f"{o.target:.2f}",
                         f"{_num(o.total_points, 0)} m²", f"{_num(o.shortfall_points, 0)} m²", yn[o.passed]])
        story += [P(L["options"], "h2"), _table(rows, [W - 122 * mm, 26 * mm, 18 * mm, 32 * mm, 30 * mm, 16 * mm],
                                                num_cols=(1, 2, 3, 4))]

    # ---- sources and disclaimer
    story.append(Spacer(1, 10))
    src = "; ".join(s.title for s in rb.sources[:3])
    story.append(P(L["disclaimer"].format(sha=getattr(r, "rulebook_sha", None) or "-") + (f" Sources: {src}." if src else ""),
                   "small"))

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Verdiq", 7.5)
        canvas.setFillColor(QUIET)
        canvas.drawString(18 * mm, 10 * mm, f"Verdiq Studio · {rb.meta.municipality} · {rb.meta.scheme} {rb.meta.version}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"{L['page']} {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def plan_png_bytes(rulebook, plan: dict, findings) -> bytes:
    """Render the imported plan (stats, mapping, plot) with findings to PNG for the report."""
    import matplotlib.pyplot as plt

    from verdiq_plan_figure import plan_figure
    fig = plan_figure(rulebook, plan["stats"], plan["mapping"], plan["plot"], findings, width_in=7.0)
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out.getvalue()
