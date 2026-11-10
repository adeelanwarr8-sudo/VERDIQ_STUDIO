"""Find and load rulebooks from a local folder or a GitHub repository release.

Layout: <root>/<country>/<municipality>/<scheme>/<version>/rulebook.yaml
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

from verdiq_schema import Rulebook


@dataclass(frozen=True)
class CatalogueEntry:
    id: str
    version: str
    country: str
    municipality: str
    scheme: str
    status: str
    name: str
    path: str  # relative to the rulebook root, e.g. se/nacka/gyf-nacka-stad/2019-10

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"


def parse_rulebook(text: str) -> Rulebook:
    return Rulebook.model_validate(yaml.safe_load(text))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


class LocalSource:
    """Rulebooks stored in a folder (monorepo or a checkout of verdiq-rulebooks)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def catalogue(self) -> list[CatalogueEntry]:
        entries = []
        for p in sorted(self.root.glob("*/*/*/*/rulebook.yaml")):
            rb = parse_rulebook(p.read_text(encoding="utf-8"))
            entries.append(CatalogueEntry(
                id=rb.meta.id, version=rb.meta.version, country=rb.meta.country,
                municipality=rb.meta.municipality, scheme=rb.meta.scheme, status=rb.meta.status,
                name=rb.meta.name.text("en"), path=str(p.parent.relative_to(self.root)).replace("\\", "/")))
        return entries

    def read_text(self, rel_path: str) -> str:
        return (self.root / rel_path).read_text(encoding="utf-8")

    def load(self, entry_path: str) -> tuple[Rulebook, str]:
        text = self.read_text(f"{entry_path}/rulebook.yaml")
        return parse_rulebook(text), sha256(text)

    def examples(self, entry_path: str) -> list[dict]:
        return [yaml.safe_load(p.read_text(encoding="utf-8"))
                for p in sorted((self.root / entry_path / "examples").glob("*.yaml"))]


class GitHubSource:
    """Rulebooks read from raw.githubusercontent.com at a pinned tag or commit.

    The repository must contain index.yaml (list of rulebooks with their paths).
    For a private repository pass a fine-grained read-only token.
    """

    def __init__(self, repo: str, ref: str, subdir: str = "", token: str | None = None):
        self.base = f"https://raw.githubusercontent.com/{repo}/{ref}/" + (subdir.strip("/") + "/" if subdir else "")
        self.token = token

    def read_text(self, rel_path: str) -> str:
        req = urllib.request.Request(self.base + rel_path)
        if self.token:
            req.add_header("Authorization", f"token {self.token}")
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - fixed https host
            return r.read().decode("utf-8")

    def catalogue(self) -> list[CatalogueEntry]:
        data = yaml.safe_load(self.read_text("index.yaml"))
        return [CatalogueEntry(**e) for e in data["rulebooks"]]

    def load(self, entry_path: str) -> tuple[Rulebook, str]:
        text = self.read_text(f"{entry_path}/rulebook.yaml")
        return parse_rulebook(text), sha256(text)


def build_index(root: str | Path) -> str:
    entries = LocalSource(root).catalogue()
    return yaml.safe_dump({"rulebooks": [e.__dict__ for e in entries]}, allow_unicode=True, sort_keys=False)


def to_json(entries: list[CatalogueEntry]) -> str:
    return json.dumps([e.__dict__ for e in entries], ensure_ascii=False, indent=2)


class FlatSource:
    """Rulebooks stored as single files next to the app: rulebook_<city>_<scheme>_<version>.yaml.

    A city's Excel cell map, if any, sits beside it as rulebook_<...>.template-map.yaml.
    """

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)

    def catalogue(self) -> list[CatalogueEntry]:
        entries = []
        for p in sorted(self.folder.glob("rulebook_*.yaml")):
            if p.name.endswith(".template-map.yaml"):
                continue
            rb = parse_rulebook(p.read_text(encoding="utf-8"))
            entries.append(CatalogueEntry(
                id=rb.meta.id, version=rb.meta.version, country=rb.meta.country,
                municipality=rb.meta.municipality, scheme=rb.meta.scheme, status=rb.meta.status,
                name=rb.meta.name.text("en"), path=p.stem))
        return entries

    def read_text(self, rel_path: str) -> str:
        # '<stem>/template-map.yaml' -> '<stem>.template-map.yaml'
        return (self.folder / rel_path.replace("/", ".")).read_text(encoding="utf-8")

    def load(self, entry_path: str) -> tuple[Rulebook, str]:
        text = (self.folder / f"{entry_path}.yaml").read_text(encoding="utf-8")
        return parse_rulebook(text), sha256(text)

    def examples(self, entry_path: str) -> list[dict]:
        return []
