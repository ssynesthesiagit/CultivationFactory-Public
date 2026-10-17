"""Dao / I Ching hooks for proposed playbooks, derived from data rather than defaults.

Dao hook -- which active Dao Aspects the line's printed action text corresponds
to.  The Aspect list is Core Rules Reference v0.2C section 17.4 (thirteen common
Aspects, four restricted; Chaos inactive) and the correspondence principle is the
Dao Aspect / Immortal Art opening rules ("like goes with like").  The keyword
table in ``rules/dao_aspects.v1.json`` mirrors the semantics the Immortal Art
authority builder already uses (``tools/build_immortal_art_authority.py``); a
keyword found in a step's printed rules text is the evidence, and the hook names
it, so a GM can see why an Aspect is claimed.  When the sheet carries an
authored Dao theme (Command 4 GM authoring, ``gm.dao.actual.*``) its core theme
leads the hook; a project-derived provisional theme is generic and is ignored.

I Ching hook -- the line's change reading: when to leave it and which proposed
playbook to shift to.  It is computed from the line's real cost against the
pool, the template's declared shift target and that target's own cost, plus the
sheet's authored I Ching theme when one exists.  The rules corpus carries no
I Ching rules text, so no hexagram lore is invented: the reading is confined to
conditions the sheet can actually check.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .rules import RULES_DIR

DEFAULT_ASPECTS_PATH = RULES_DIR / "dao_aspects.v1.json"
ASPECTS_SCHEMA_VERSION = "TianxiaFoundry.CompositePlaybookDaoAspects.v1"
SHIFT_KINDS = ("resource_low", "resource_recovered", "step_denied")
PROVISIONAL_MARKER = ".project."


@dataclass(frozen=True)
class Aspect:
    aspect_id: str
    display_name: str
    restricted: bool
    keywords: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True)
class AspectTable:
    schema_version: str
    aspects: tuple[Aspect, ...]
    max_per_playbook: int = 2
    match_restricted: bool = False

    @classmethod
    def from_mapping(cls, mapping: Any) -> "AspectTable":
        if not isinstance(mapping, Mapping) or mapping.get("schema_version") != ASPECTS_SCHEMA_VERSION:
            raise ValueError(f"aspects document must declare schema_version {ASPECTS_SCHEMA_VERSION!r}")
        rows = mapping.get("aspects")
        if not isinstance(rows, list) or not rows:
            raise ValueError("aspects must be a non-empty list")
        aspects: list[Aspect] = []
        for index, row in enumerate(rows):
            where = f"aspects[{index}]"
            if not isinstance(row, Mapping):
                raise ValueError(f"{where}: aspect must be an object")
            aspect_id, name = row.get("aspect_id"), row.get("display_name")
            if not isinstance(aspect_id, str) or not aspect_id or not isinstance(name, str) or not name:
                raise ValueError(f"{where}: aspect_id and display_name must be non-empty strings")
            keywords = row.get("keywords") or []
            if isinstance(keywords, str) or not keywords or not all(isinstance(k, str) and k.strip() for k in keywords):
                raise ValueError(f"{where}: keywords must be a non-empty list of strings")
            restricted = row.get("restricted", False)
            if not isinstance(restricted, bool):
                raise ValueError(f"{where}: restricted must be a boolean")
            words = tuple(k.strip().casefold() for k in keywords)
            aspects.append(Aspect(aspect_id, name, restricted, words,
                                  tuple(re.compile(rf"\b{re.escape(w)}\w*", re.I) for w in words)))
        ids = [a.aspect_id for a in aspects]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate aspect_id in aspects")
        max_per = mapping.get("max_aspects_per_playbook", 2)
        if isinstance(max_per, bool) or not isinstance(max_per, int) or max_per < 1:
            raise ValueError("max_aspects_per_playbook must be a positive integer")
        match_restricted = mapping.get("match_restricted", False)
        if not isinstance(match_restricted, bool):
            raise ValueError("match_restricted must be a boolean")
        return cls(mapping["schema_version"], tuple(aspects), max_per, match_restricted)

    def get(self, aspect_id: str) -> Aspect | None:
        return next((a for a in self.aspects if a.aspect_id == aspect_id), None)


def load_aspects(path: Path | None = None) -> AspectTable:
    """Load and validate the Dao Aspect keyword table; defaults to ``DEFAULT_ASPECTS_PATH``."""
    source = Path(path) if path is not None else DEFAULT_ASPECTS_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"aspects file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"aspects file {source} is not valid JSON: {exc}") from exc
    return AspectTable.from_mapping(raw)


def aspect_hits(table: AspectTable, text: str) -> dict[str, dict[str, int]]:
    """``{aspect_id: {keyword: count}}`` for every keyword found in ``text`` (restricted Aspects only when enabled)."""
    hits: dict[str, dict[str, int]] = {}
    for aspect in table.aspects:
        if aspect.restricted and not table.match_restricted:
            continue
        found = {word: len(pattern.findall(text)) for word, pattern in zip(aspect.keywords, aspect.patterns)}
        found = {word: count for word, count in found.items() if count}
        if found:
            hits[aspect.aspect_id] = found
    return hits


@dataclass(frozen=True)
class Themes:
    """The sheet's own Dao / I Ching themes when authored; provisional project-derived text is ignored."""

    dao_phrase: str | None = None
    dao_source: str | None = None
    dao_note: str = "no Dao theme on the sheet"
    i_ching_phrase: str | None = None
    i_ching_source: str | None = None
    i_ching_note: str = "no I Ching theme on the sheet"

    def to_dict(self) -> dict[str, Any]:
        return {"dao": {"phrase": self.dao_phrase, "source": self.dao_source, "note": self.dao_note},
                "i_ching": {"phrase": self.i_ching_phrase, "source": self.i_ching_source, "note": self.i_ching_note}}


def _theme(block: Any, kind: str) -> tuple[str | None, str | None, str]:
    if not isinstance(block, Mapping):
        return None, None, f"no {kind} theme on the sheet"
    authoring_id = block.get("authoring_id") if isinstance(block.get("authoring_id"), str) else None
    if authoring_id and PROVISIONAL_MARKER in authoring_id:
        return None, authoring_id, f"provisional project-derived {kind} theme ignored (generic text)"
    parts = [str(block[key]).strip() for key in ("core_theme", "tactical_expression")
             if isinstance(block.get(key), str) and str(block[key]).strip()]
    if not parts:
        return None, authoring_id, f"{kind} theme carries no core_theme"
    name = block.get("display_name")
    prefix = f"{name.strip()}: " if isinstance(name, str) and name.strip() else ""
    return prefix + " ".join(parts), authoring_id or "sheet", f"authored {kind} theme"


def themes_from_surface(data: Any) -> Themes:
    """Read the projected ``surfaces.dao_i_ching.data`` document; anything missing yields an empty theme."""
    if not isinstance(data, Mapping):
        return Themes()
    nested = data.get("dao_i_ching") if isinstance(data.get("dao_i_ching"), Mapping) else {}
    dao = data.get("dao") if isinstance(data.get("dao"), Mapping) else nested.get("dao")
    i_ching = data.get("i_ching") if isinstance(data.get("i_ching"), Mapping) else nested.get("i_ching")
    dao_phrase, dao_source, dao_note = _theme(dao, "Dao")
    ic_phrase, ic_source, ic_note = _theme(i_ching, "I Ching")
    return Themes(dao_phrase, dao_source, dao_note, ic_phrase, ic_source, ic_note)


def build_dao_hook(steps: Iterable[tuple[str, str]], table: AspectTable,
                   themes: Themes | None = None) -> tuple[str, list[dict[str, Any]]]:
    """``steps`` are (display_name, printed rules text) pairs.  Returns (hook text, structured Aspect evidence)."""
    evidence: dict[str, dict[str, dict[str, int]]] = {}
    for name, text in steps:
        for aspect_id, found in aspect_hits(table, text or "").items():
            evidence.setdefault(aspect_id, {})[name] = found
    ranked = sorted(evidence.items(),
                    key=lambda item: (-sum(sum(f.values()) for f in item[1].values()), item[0]))[:table.max_per_playbook]
    aspects: list[dict[str, Any]] = []
    phrases: list[str] = []
    for aspect_id, by_step in ranked:
        aspect = table.get(aspect_id)
        label = aspect.display_name if aspect else aspect_id
        aspects.append({"aspect_id": aspect_id, "display_name": label,
                        "evidence": [{"action": name, "keywords": dict(found)} for name, found in by_step.items()]})
        detail = "; ".join(f"{name}: " + ", ".join(f"{w} x{c}" for w, c in found.items()) for name, found in by_step.items())
        phrases.append(f"{label} ({detail})")
    parts: list[str] = []
    if themes is not None and themes.dao_phrase:
        parts.append(f"Dao: {themes.dao_phrase}")
    if phrases:
        parts.append("The printed text of this line corresponds to the Dao Aspect" + ("s " if len(phrases) > 1 else " ")
                     + " and ".join(phrases) + " (Core Rules 17.4; like goes with like, so the correspondence is direct).")
    else:
        parts.append("No active Dao Aspect keyword appears in the printed text of these steps, so the line claims no "
                     "Aspect; it follows the character's selected Path and Spheres as printed.")
    return " ".join(parts), aspects


def build_i_ching_hook(*, tendency: str | None, shift_when: str, shift_to: str | None, shift_to_proposed: bool,
                       shift_to_spent: int, spent: int, pool_name: str, limit: int | None,
                       fallback_name: str | None, themes: Themes | None = None) -> str:
    """The line's change reading from real numbers: when to leave it and where to shift."""
    if shift_when not in SHIFT_KINDS:
        raise ValueError(f"shift_when must be one of {SHIFT_KINDS}, got {shift_when!r}")
    parts: list[str] = []
    if themes is not None and themes.i_ching_phrase:
        parts.append(f"I Ching: {themes.i_ching_phrase}")
    if tendency:
        parts.append(f"Tendency: {tendency.rstrip('.')}.")
    hold = f"hold the zero-cost fallback {fallback_name}" if fallback_name else "hold the action"
    if not shift_to:
        target = hold
    elif shift_to_proposed:
        target = f"shift to {shift_to}"
    else:
        target = f"{hold} ({shift_to} is not proposed for this character)"
    of_limit = f" of {limit}" if limit is not None else ""
    if shift_when == "resource_low":
        if spent > 0:
            parts.append(f"Change when {pool_name} falls below {spent}{of_limit}: this line can no longer be paid; {target}.")
        else:
            parts.append(f"This line costs no {pool_name}, so a low pool is not its change signal; {target} only when a step is denied.")
    elif shift_when == "resource_recovered":
        threshold = max(int(shift_to_spent), 1)
        parts.append(f"Change when {pool_name} is at or above {threshold}{of_limit} and an opening is present: {target} to commit.")
    else:
        parts.append(f"Change when a step of this line is denied (its slot already spent, its trigger absent, or its target out of reach): {target}.")
    return " ".join(parts)
