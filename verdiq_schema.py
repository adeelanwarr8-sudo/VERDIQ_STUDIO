"""Pydantic models for the Verdiq rulebook format (one YAML file per city scheme version)."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sv: str | None = None
    en: str | None = None
    de: str | None = None
    fi: str | None = None

    def text(self, lang: str = "en") -> str:
        return getattr(self, lang, None) or self.en or self.sv or self.de or self.fi or ""


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: Label
    country: str
    municipality: str
    scheme: str
    version: str
    effective_from: date | None = None
    effective_to: date | None = None
    status: Literal["draft", "verified", "deprecated"] = "draft"
    supersedes: str | None = None
    superseded_by: str | None = None
    crs: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["en"])


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    url: str | None = None
    pages: str | None = None
    note: str | None = None
    retrieved: date | None = None


class Score(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["weighted_area_ratio"] = "weighted_area_ratio"
    rounding: int = 2


class TargetRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lt: float | None = None
    lte: float | None = None
    gt: float | None = None
    gte: float | None = None
    target: float
    balancing_min_share: float | None = None

    def matches(self, x: float) -> bool:
        return ((self.lt is None or x < self.lt) and (self.lte is None or x <= self.lte)
                and (self.gt is None or x > self.gt) and (self.gte is None or x >= self.gte))


class Targets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["fixed", "lookup"]
    target: float | None = None
    by: str | None = None
    table: list[TargetRow] = Field(default_factory=list)
    variants: dict[str, dict[str, Any]] = Field(default_factory=dict)
    allow_project_override: bool = True
    note: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.type == "fixed" and self.target is None:
            raise ValueError("fixed targets need 'target'")
        if self.type == "lookup" and (not self.by or not self.table):
            raise ValueError("lookup targets need 'by' and 'table'")
        return self


class BalancingGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: Label
    min_share: float | None = None
    max_count: int | None = None


class ExclusiveSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str]
    text: str | None = None


class Balancing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["factor_count", "est_matrix", "none"]
    status: Literal["verified", "unverified"] = "unverified"
    required: bool = True          # False: shares are reported, but there is no pass/fail requirement
    rule: str | None = None
    groups: list[BalancingGroup] = Field(default_factory=list)
    exclusive_sets: list[ExclusiveSet] = Field(default_factory=list)
    est_matrix: Any = None
    fallback: Literal["group_flags"] | None = None


class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["min_area", "max_count", "requires_total", "requires_any"]
    value: float | None = None
    of: list[str] = Field(default_factory=list)
    min_value: float | None = None
    severity: Literal["warning", "error"] = "warning"
    text: str | None = None


class Factor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["base", "supplementary"]
    section: str
    factor: float
    measure: Literal["area", "count", "length"]
    unit_area_m2: float | None = None
    template_unit_area_m2: float | None = None
    groups: list[str] = Field(default_factory=list)
    label: Label
    constraints: list[Constraint] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.measure == "count" and self.unit_area_m2 is None:
            raise ValueError(f"{self.id}: count factors need unit_area_m2")
        if self.factor < 0:
            raise ValueError(f"{self.id}: negative factor")
        return self


class CadLayers(BaseModel):
    """A municipality's CAD layer standard: layer-name code -> factor id."""
    model_config = ConfigDict(extra="forbid")
    standard: str
    code_pattern: str
    plot_boundary_layer_pattern: str | None = None
    codes: dict[str, str]


class WithinRule(BaseModel):
    """Elements or overlays of `factors` must lie within surfaces of `within`."""
    model_config = ConfigDict(extra="forbid")
    factors: list[str]
    within: list[str]
    severity: Literal["warning", "error"] = "warning"
    text: str | None = None
    source: Literal["city_rule", "verdiq_check"] = "verdiq_check"


class Spatial(BaseModel):
    """Geometry rules used when a drawing is imported (Excel cannot check these)."""
    model_config = ConfigDict(extra="forbid")
    ground_partition: list[str] = Field(default_factory=list)   # ground surfaces that must not overlap
    roof: list[str] = Field(default_factory=list)               # surfaces on buildings (not part of the ground)
    overlays_on_base: bool = True                                # area qualities must sit on a base surface
    planting_qualities: list[str] = Field(default_factory=list)  # qualities advice may add on existing planting
    # quality -> surfaces it needs (any one); advice never proposes a quality whose surface is not in the design
    quality_requires: dict[str, list[str]] = Field(default_factory=dict)
    within_rules: list[WithinRule] = Field(default_factory=list)
    note: str | None = None

    def all_ids(self) -> set[str]:
        ids = set(self.ground_partition) | set(self.roof) | set(self.planting_qualities) | set(self.quality_requires)
        ids |= {x for v in self.quality_requires.values() for x in v}
        for r in self.within_rules:
            ids |= set(r.factors) | set(r.within)
        return ids


class Rulebook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meta: Meta
    sources: list[Source] = Field(default_factory=list)
    score: Score = Field(default_factory=Score)
    targets: Targets
    balancing: Balancing
    cad_layers: CadLayers | None = None
    spatial: Spatial | None = None
    factors: list[Factor]

    @model_validator(mode="after")
    def _check(self):
        ids = [f.id for f in self.factors]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate factor ids: {sorted(dupes)}")
        known = set(ids)
        group_ids = {g.id for g in self.balancing.groups}
        for f in self.factors:
            bad = set(f.groups) - group_ids
            if bad and self.balancing.method != "none":
                raise ValueError(f"{f.id}: unknown groups {sorted(bad)}")
            for x in f.excludes:
                if x not in known:
                    raise ValueError(f"{f.id}: excludes unknown factor {x}")
            for c in f.constraints:
                for x in c.of:
                    if x not in known:
                        raise ValueError(f"{f.id}: constraint refers to unknown factor {x}")
        for s in self.balancing.exclusive_sets:
            for x in s.ids:
                if x not in known:
                    raise ValueError(f"exclusive set refers to unknown factor {x}")
        if self.cad_layers:
            for code, fid in self.cad_layers.codes.items():
                if fid not in known:
                    raise ValueError(f"CAD layer {code} maps to unknown factor {fid}")
        if self.spatial:
            bad = self.spatial.all_ids() - known
            if bad:
                raise ValueError(f"spatial rules refer to unknown factors {sorted(bad)}")
        return self

    @property
    def key(self) -> str:
        return f"{self.meta.id}@{self.meta.version}"

    def factor(self, fid: str) -> Factor:
        for f in self.factors:
            if f.id == fid:
                return f
        raise KeyError(fid)
