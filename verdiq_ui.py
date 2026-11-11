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
    """English project sidebar; rulebook metadata is the single source of truth."""
    st.set_page_config(page_title=product, page_icon="🌿", layout="wide", initial_sidebar_state="expanded")
    ss = st.session_state
    ss.setdefault("rb_key", None)
    ss.setdefault("proj_name", "")
    ss.setdefault("proj_type", "Residential")
    ss.setdefault("proj_prop", "")
    ss.setdefault("proj_author", "")
    catalogue = get_catalogue()
    if not catalogue:
        st.error("No municipal GYF rulebooks are available. Check the GitHub rulebook configuration.")
        st.stop()

    # The rulebooks currently shipped with Verdiq are all Swedish. Country is not
    # an extra sidebar field: it is derived from the selected catalogue entry.
    with st.sidebar:
        st.markdown("### Project Setup")
        st.caption("Define project parameters and the applicable GYF model.")
        st.text_input("Project Name", key="proj_name", placeholder="Enter project name")
        st.selectbox("Project Type", ["Residential", "Commercial", "Mixed-use", "School / Preschool",
                                       "Public facility", "Other"], key="proj_type")
        st.text_input("Project Site Address", key="proj_prop", placeholder="Street, city, Sweden")

        munis = sorted({e.municipality for e in catalogue})
        muni = st.selectbox("Municipality", munis,
                            index=munis.index("Nacka") if "Nacka" in munis else 0,
                            key="vq_municipality")
        versions = sorted((e for e in catalogue if e.municipality == muni),
                          key=lambda e: e.version, reverse=True)
        entry = st.selectbox("GYF Version", versions, key="vq_version",
                             format_func=lambda e: f"{e.scheme} · {e.version}" +
                             ("" if e.status == "verified" else f" ({e.status})"))
        rb, sha = get_rulebook(entry.path)
        lang = "en"  # Swedish localization intentionally deferred.
        if ss.rb_key and ss.rb_key != rb.key and on_rulebook_change:
            on_rulebook_change(rb)
        ss.rb_key = rb.key

        source = rb.sources[0] if rb.sources else None
        source_title = source.title if source else rb.meta.name.text("sv")
        # A rulebook may represent an independent certifier, not a municipality.
        publisher = "Sweden Green Building Council (SGBC)" if rb.meta.scheme == "MB-GYF" else f"{rb.meta.municipality} municipality"
        import html
        with st.container(border=True):
            st.markdown("**Model and Source**")
            st.markdown(f"{html.escape(source_title)}  \n**Publisher:** {html.escape(publisher)}  \n"
                        f"**Version:** {html.escape(rb.meta.version)}")
            st.caption(f"Rulebook status: {rb.meta.status.capitalize()} · Fingerprint: {sha}")
            if source and source.url:
                st.link_button("Official source", source.url, use_container_width=True)
        if rb.meta.superseded_by:
            st.warning(f"Superseded by {rb.meta.superseded_by}; verify the applicable version for this project.")
        if rb.meta.status != "verified":
            st.warning("Some rulebook rules are under review. Do not treat results as fully verified.")

        use_override = st.checkbox("Project-specific GYF target",
                                   help="Use only when the municipality has issued an applicable project-specific GYF requirement.",
                                   disabled=not rb.targets.allow_project_override,
                                   key="vq_override_enabled")
        override = st.number_input("Target", min_value=0.0, max_value=3.0, value=0.60,
                                   step=0.05, format="%.2f", key="vq_target") if use_override else None
        built_share = None
        if rb.targets.type == "lookup":
            built_share = st.number_input("Built-up share of plot (%)", min_value=0.0, max_value=100.0,
                                          value=float(ss.get("built", 60.0)), step=1.0,
                                          help="Required to select a default GYF target for this rulebook.",
                                          key="built_share_entry")
            ss.built = built_share
        # Apply DXF-derived plot area before constructing its number_input widget.
        pending_area = ss.pop("_plot_area_next", None)
        if pending_area is not None:
            ss["plot_area"] = float(pending_area)
        ss.setdefault("plot_area", 2000.0)
        plot_area = st.number_input("Plot Area (m²)", min_value=0.0, step=10.0,
                                    key="plot_area", help="Imported plot boundaries can update this value on confirmation.")
        with st.expander("Municipal requirements & guidance", expanded=False):
            st.write(rb.targets.note or "Check the project's official GYF documentation for the applicable target.")
            if rb.balancing:
                st.write(rb.balancing.rule or "Review the municipality's balancing methodology.")
            st.caption("Only the selected rulebook's encoded requirements are used in calculations.")

    return SimpleNamespace(rb=rb, sha=sha, lang=lang, entry=entry, muni=muni,
                           built_share=built_share, override=override, plot_area=plot_area,
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
