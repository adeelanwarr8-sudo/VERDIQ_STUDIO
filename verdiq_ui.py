"""Streamlit pieces shared by Verdiq Studio and Verdiq Review: rulebook source, rulebook picker, plan display."""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import streamlit as st
import yaml

from verdiq_loader import FlatSource, GitHubSource

APP_DIR = Path(__file__).resolve().parent   # every file of Verdiq Studio lives in this one folder
SEV_ICON = {"error": "🔴", "warning": "🟠", "info": "🔵"}


def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:  # no secrets file
        return default


@st.cache_resource
def get_source():
    """Rulebooks from GitHub (pinned tag in secrets) or the rulebook_*.yaml files next to the app."""
    repo, ref = _secret("RULEBOOK_REPO"), _secret("RULEBOOK_REF")
    if repo and ref:
        return GitHubSource(repo, ref, subdir=_secret("RULEBOOK_SUBDIR", ""), token=_secret("GITHUB_TOKEN"))
    return FlatSource(APP_DIR)


@st.cache_data(ttl=3600)
def get_catalogue():
    return get_source().catalogue()


@st.cache_data(ttl=3600)
def get_rulebook(path):
    return get_source().load(path)


def get_template_map(path):
    try:
        return yaml.safe_load(get_source().read_text(f"{path}/template-map.yaml"))
    except Exception:
        return None


def save_upload(upload, suffix):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(upload.getvalue())
        return tmp.name


def setup(product: str, tagline: str, on_rulebook_change=None) -> SimpleNamespace:
    """Page config, sidebar rulebook picker and target inputs. Returns the shared context."""
    st.set_page_config(page_title=product, page_icon="🌿", layout="wide")
    ss = st.session_state
    ss.setdefault("rb_key", None)
    catalogue = get_catalogue()
    with st.sidebar:
        st.title(product)
        st.caption(tagline)
        st.divider()
        countries = sorted({e.country for e in catalogue})
        country = st.selectbox("Country", countries)
        munis = sorted({e.municipality for e in catalogue if e.country == country})
        muni = st.selectbox("Municipality", munis, index=munis.index("Nacka") if "Nacka" in munis else 0)
        versions = sorted([e for e in catalogue if e.country == country and e.municipality == muni],
                          key=lambda e: e.version, reverse=True)
        entry = st.selectbox("Scheme and version", versions,
                             format_func=lambda e: f"{e.scheme} {e.version}" + ("" if e.status == "verified" else f" ({e.status})"))
        rb, sha = get_rulebook(entry.path)
        lang = st.radio("Language", ["en", "sv"], horizontal=True, index=0 if "en" in rb.meta.languages else 1)
        if ss.rb_key and ss.rb_key != rb.key and on_rulebook_change:
            on_rulebook_change(rb)
        ss.rb_key = rb.key
        st.divider()
        built_share = None
        if rb.targets.type == "lookup":
            built_share = st.number_input("Share of plot built over (%)", 0.0, 100.0, float(ss.get("built", 60.0)), 1.0)
            ss.built = built_share
        use_override = st.checkbox("Project-specific target (from the city's GYF-underlag)",
                                   disabled=not rb.targets.allow_project_override)
        override = st.number_input("Target", 0.0, 3.0, 0.6, 0.05) if use_override else None

    status_note = {"verified": "verified against the city's own calculations",
                   "draft": "draft: score verified, some rules still open"}.get(rb.meta.status, rb.meta.status)
    st.markdown(f"**{rb.meta.name.text(lang)}** · {rb.meta.municipality} · version {rb.meta.version} · "
                f"rulebook `{sha}` · _{status_note}_")
    if rb.meta.superseded_by:
        st.warning(f"This version is superseded by {rb.meta.superseded_by}. Use it only for projects started under it.")
    return SimpleNamespace(rb=rb, sha=sha, lang=lang, entry=entry, muni=muni, built_share=built_share, override=override,
                           calc_kw=dict(built_share_pct=built_share, target_override=override, lang=lang),
                           lab=lambda fid: rb.factor(fid).label.text(lang))


def findings_list(findings):
    located = [f for f in findings if f.location and f.severity in ("error", "warning")]
    for f in findings:
        n = f" [{located.index(f) + 1}]" if f in located else ""
        st.markdown(f"{SEV_ICON[f.severity]}{n} {f.text}" + (" · _city rule_" if f.source == "city_rule" else ""))


def show_plan(rb, plan, findings):
    from verdiq_plan_figure import plan_figure
    st.pyplot(plan_figure(rb, plan["stats"], plan["mapping"], plan["plot"], findings), width="stretch")
