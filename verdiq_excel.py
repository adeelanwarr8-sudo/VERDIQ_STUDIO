"""Write Verdiq quantities into a municipality's own Excel template (cell map in template-map.yaml).

Verdiq writes inputs only; the city's own formulas compute the score, so the submitted file is the
city's file. Reading the recalculated outputs back gives an independent consistency check.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import openpyxl
import yaml


def load_template_map(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def fill_template(template_xlsx: str | Path, template_map: dict, inputs: dict[str, float],
                  plot_area_m2: float, out_path: str | Path, header: dict[str, str] | None = None,
                  built_share_pct: float | None = None) -> Path:
    wb = openpyxl.load_workbook(template_xlsx)
    ws = wb[template_map["sheet"]]
    for fid, cell in template_map["inputs"].items():
        ws[cell] = float(inputs.get(fid, 0) or 0)
    ws[template_map["plot_area_cell"]] = float(plot_area_m2)
    if template_map.get("built_area_cell") and built_share_pct is not None:
        ws[template_map["built_area_cell"]] = round(float(plot_area_m2) * float(built_share_pct) / 100, 2)
    for cell, text in (header or {}).items():
        ws[cell] = text
    out = Path(out_path)
    wb.save(out)
    return out


def recalculate_with_libreoffice(xlsx: str | Path) -> Path:
    """Recalculate all formulas headlessly (LibreOffice) and return the path of the recalculated copy."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice not found")
    outdir = Path(tempfile.mkdtemp(prefix="verdiq_recalc_"))
    subprocess.run([soffice, "--headless", "--calc", "--convert-to", "xlsx:Calc MS Excel 2007 XML",
                    "--outdir", str(outdir), str(xlsx)], check=True, capture_output=True, timeout=180)
    return outdir / Path(xlsx).name


def read_outputs(xlsx: str | Path, template_map: dict) -> dict:
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb[template_map["sheet"]]
    o = template_map["outputs"]
    out = {"total_points": ws[o["total_points"]].value, "score": ws[o["score"]].value,
           "balancing_achieved": {g: ws[c].value for g, c in o["balancing_achieved"].items()}}
    if o.get("target"):
        out["target"] = ws[o["target"]].value
    return out
