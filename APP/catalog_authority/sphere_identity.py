"""Stable Aspect identities from CAT1; the Bible table supplies display aliases."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata

from tools.aspect_terms import TERMS, aspect_terms


_APP = Path(__file__).resolve().parents[1]
_SPHERES = "catalog_authority/cat1/data/canonical_spheres.v1.json"
_ALIASES = "catalog_authority/cat1/data/sphere_aliases_and_labels.v1.json"
_BACKGROUND_ROUTES = "catalog_authority/cat1/data/background_origin_talent_routes.v1.json"
SPHERE_ID_PREFIX = "tianxia.sphere."
_BACKGROUND_SPHERE_PREFIX = "tianxia.background_sphere."
_BACKGROUND_TALENT_PREFIX = "tianxia.background_talent."
_OLD_HEADING = re.compile(r"^Sphere of\s+(.+)$", re.I)
_NEW_HEADING = re.compile(r"^Way of\s+\S", re.I)
_MARKER_SUFFIX = re.compile(r"\s+(?:Sphere|Aspect)$", re.I)


class UnknownSphereLabel(ValueError):
    """An authored label had no canonical Aspect identity."""


def _key(label: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", label).casefold()))


def _label_key(label: str) -> str:
    """Normalize both legacy and current printed labels before joining identities."""
    label = aspect_terms(label)
    short_names = {_key(old): new for old, new in TERMS["short_lists"].items()}
    return _key(short_names.get(_key(label), label))


def _records(root: Path, path: str) -> list[dict]:
    return json.loads((root / path).read_text(encoding="utf-8"))["records"]


def sphere_heading_label(title: str) -> str | None:
    """Extract a label only from old or new Aspect heading grammar."""
    label = title.strip()
    for old, new in TERMS["heading_suffixes"].items():
        label = label.removesuffix(old).rstrip()
        if new != "unchanged":
            label = label.removesuffix(new).rstrip()
    if old := _OLD_HEADING.fullmatch(label):
        return old[1]
    return label if _NEW_HEADING.match(label) else None


def sphere_marker_label(text: str) -> str | None:
    """Extract an explicit Background bullet marker, not an unmarked Talent name."""
    label = text.strip().removesuffix(".").strip()
    return sphere_heading_label(label) or (_MARKER_SUFFIX.sub("", label) if _MARKER_SUFFIX.search(label) else None)


@lru_cache(maxsize=None)
def _sphere_labels(root: Path) -> dict[str, str]:
    labels: dict[str, str] = {}

    def add(label: str, sphere_id: str) -> None:
        key = _label_key(label)
        if labels.setdefault(key, sphere_id) != sphere_id:
            raise ValueError(f"Conflicting Aspect identities for {label!r}: {labels[key]}, {sphere_id}")

    for row in _records(root, _SPHERES):
        name = row["display_name"]
        sphere_id = row["canonical_sphere_id"]
        add(name, sphere_id)
        for alias in row["aliases"]:
            add(alias, sphere_id)
    for row in _records(root, _ALIASES):
        if row.get("canonical_sphere_id"):
            add(row["label"], row["canonical_sphere_id"])

    aliases = TERMS["aliases_other_spellings_to_short_name"]
    for spelling, name in aliases.items():
        known = labels.get(_label_key(spelling)) or labels.get(_label_key(name))
        if known:
            add(name, known)
            add(spelling, known)
    for name, full in TERMS["names"].items():
        add(full, labels[_label_key(name)])
    for old, short in TERMS["short_lists"].items():
        if sphere_id := labels.get(_label_key(old)):
            add(short, sphere_id)
    for old, short in TERMS["short_lists"].items():
        add(old, labels[_label_key(short)])
    return labels


def resolve_sphere_id(label: str, *, root: Path = _APP) -> str:
    """Resolve a printed old/new full name, short name, alias, or heading."""
    key = _label_key(sphere_heading_label(label) or label)
    labels = _sphere_labels(root)
    try:
        return labels[key]
    except KeyError:
        raise UnknownSphereLabel(f"Unknown Aspect label: {label!r}") from None


_old_entry_names = {
    _key(new): old for old, new in TERMS["entry_names_that_changed"].items()
}


def talent_identity_name(display_name: str) -> str:
    """Use the prior entry name as the join key, without changing display text."""
    return _old_entry_names.get(_key(display_name), display_name)


@lru_cache(maxsize=1)
def background_route_ids() -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Read existing supplement IDs keyed by canonical Aspect and Talent label.

    Background IDs are a separate namespace: the historical Harvest routes
    spell their suffix differently from the ordinary Aspect record.
    """
    spheres: dict[str, str] = {}
    talents: dict[tuple[str, str], str] = {}
    for row in _records(_APP, _BACKGROUND_ROUTES):
        label = row["canonical_sphere_name"]
        canonical = row.get("canonical_sphere_id") or resolve_sphere_id(label)
        talent_id = row["background_route_record_id"]
        suffix, sep, _ = talent_id.removeprefix(_BACKGROUND_TALENT_PREFIX).partition(".")
        if not sep:
            raise ValueError(f"Malformed Background Talent identity: {talent_id!r}")
        sphere_id = _BACKGROUND_SPHERE_PREFIX + suffix
        if spheres.setdefault(canonical, sphere_id) != sphere_id:
            raise ValueError(f"Conflicting Background Aspect identities for {canonical}")
        name = row["display_name"].removesuffix(f" ({label})")
        key = canonical, background_talent_key(name)
        if talents.setdefault(key, talent_id) != talent_id:
            raise ValueError(f"Conflicting Background Talent identities for {key!r}")
    return spheres, talents


@lru_cache(maxsize=1)
def _background_talent_owners() -> dict[str, str]:
    return {talent_id: sphere_id for (sphere_id, _), talent_id in background_route_ids()[1].items()}


def projected_talent_sphere_id(talent_id: str | None, owner_id: str | None, label: str | None) -> str | None:
    """Resolve a selected Talent's Aspect, including historical Background routes."""
    if isinstance(talent_id, str) and (sphere_id := _background_talent_owners().get(talent_id)):
        return sphere_id
    return projected_sphere_id(owner_id, label)


def background_talent_key(name: str) -> str:
    return _key(talent_identity_name(name))


@lru_cache(maxsize=1)
def _acquisition_ids() -> dict[str, str]:
    canonical = set(_sphere_labels(_APP).values())
    return {
        **{sphere_id: sphere_id for sphere_id in canonical},
        **{background: sphere_id for sphere_id, background in background_route_ids()[0].items()},
    }


def acquired_sphere_id(record_id: str | None) -> str | None:
    """Return the creator choice ID for a canonical or Background acquisition."""
    return _acquisition_ids().get(record_id) if isinstance(record_id, str) else None


def projected_sphere_id(record_id: str | None, label: str | None) -> str | None:
    """Read a saved display link without inventing IDs for unlinked rows."""
    if sphere_id := acquired_sphere_id(record_id):
        return sphere_id
    if isinstance(label, str) and label.strip():
        try:
            return resolve_sphere_id(label)
        except UnknownSphereLabel:
            pass
    return None
