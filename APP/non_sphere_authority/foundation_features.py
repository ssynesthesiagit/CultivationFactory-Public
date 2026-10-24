"""Foundation Feature blocks by stage, from the playable Foundations catalog (owner 2026-09-25).

A finished character's owner sheet carries ``foundation.mechanics.source_passives``
(numeric bonuses already applied at creation, see ``foundation_mechanics.py``) but
not the Foundation's other printed features, and combat never sees them either.
This module reads the same verified catalog records ``foundation_mechanics.py``
uses (``foundation_corpus_release`` + the pinned runtime registry) and returns
every printed feature block -- "## 4. Foundation Features", the resource's own
generation trigger under "## 3. Foundation Resource", and the cumulative
blocks under "## 5. Stage Progression" -- tagged with the stage it becomes
available at, for the typed mechanics authority and the combat compiler.
"""
from __future__ import annotations

import re
from typing import Any

from . import foundation_mechanics as _fm

# One progression for every Foundation. The catalog's shared "Integrated or
# Intermediate Expressions" heading uses Intermediate for the same tier.
# Latent has no currently printed feature blocks; Unstable is not a stable tier.
STAGE_ORDER = ("Latent", "Common Expression", "Awakened", "Integrated", "Refined", "Perfected")
_STAGE_ALIASES = {"Intermediate": "Integrated"}
_STAGE_RE = re.compile(r"\b(?:" + "|".join(re.escape(stage) for stage in (*STAGE_ORDER, *_STAGE_ALIASES)) + r")\b", re.IGNORECASE)
_STAGE_NAMES = {stage.casefold(): stage for stage in (*STAGE_ORDER, *_STAGE_ALIASES)}

_FIELD_RE = re.compile(r"^\*\*([^*]+):\*\* (.+)$", re.MULTILINE)


def _slug(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def feature_id(foundation_id: str, name: str) -> str:
    return f"foundation.{foundation_id}.{_slug(name)}"


def _stage_tier(available_at: str | None, default: str = "Awakened") -> str:
    """Read the first printed tier, before qualifiers such as 'improves at'."""
    match = _STAGE_RE.search(available_at or "")
    if match is None:
        return default
    stage = _STAGE_NAMES[match.group().casefold()]
    return _STAGE_ALIASES.get(stage, stage)


def _blocks(text: str) -> list[tuple[str, dict[str, str]]]:
    """Every ``#### Name`` block's bolded fields, stopping at the next ``### `` heading
    (same trick as ``foundation_mechanics.foundation_passive_definitions``)."""
    out = []
    for chunk in re.split(r"^#### ", text, flags=re.MULTILINE)[1:]:
        name, _, body = chunk.partition("\n")
        body = re.split(r"^### ", body, maxsplit=1, flags=re.MULTILINE)[0]
        fields = dict(_FIELD_RE.findall(body))
        if fields:
            out.append((name.strip(), fields))
    return out


def _resource_generation_blocks(resource_text: str) -> list[tuple[str, dict[str, str]]]:
    """The resource section's own feature block (e.g. "Generate Mirror Trace"), not
    its plain ``### <Resource Name>`` rules table (which has no ``**Type:**`` field)."""
    out = []
    for chunk in re.split(r"^### ", resource_text, flags=re.MULTILINE)[1:]:
        name, _, body = chunk.partition("\n")
        fields = dict(_FIELD_RE.findall(body))
        if fields.get("Type"):
            out.append((name.strip(), fields))
    return out


def foundation_feature_blocks(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Every printed feature of one verified Foundation record, tagged by stage.

    A name already found (section 4's base features, or the resource's own
    generation trigger) is not repeated if "Stage Progression" recaps it; only
    progression subsections add new blocks at their printed availability.
    Their heading is a minimum tier: an evolved block that repeats its base
    feature's availability must still require that evolution's stage.
    """
    surfaces = record["semantic_surfaces"]
    seen: dict[str, dict[str, Any]] = {}
    for name, fields in [*_blocks(surfaces["features"]), *_resource_generation_blocks(surfaces["resource"])]:
        seen.setdefault(name, {"name": name, "stage": _stage_tier(fields.get("Available At")), "fields": fields})
    for stage_chunk in re.split(r"^### ", surfaces["progression"], flags=re.MULTILINE)[1:]:
        header, _, rest = stage_chunk.partition("\n")
        stage = _stage_tier(header, default="")
        if not stage:
            continue
        for name, fields in _blocks(rest):
            available = _stage_tier(fields.get("Available At"), default=stage)
            minimum = max((stage, available), key=STAGE_ORDER.index)
            seen.setdefault(name, {"name": name, "stage": minimum, "fields": fields})
    return list(seen.values())


def features_for_stage(foundation_id: str, stage: str | None) -> list[dict[str, Any]]:
    """Every feature available at or below ``stage`` (cumulative), catalog order.

    An unrecognized or unstable stage (e.g. a Foundation's alternate "Unstable"
    initial state) grants none, matching how the initial-mechanics layer already
    treats an unstable Foundation as unable to claim its stable benefits.
    """
    if not isinstance(stage, str):
        return []
    stage = _STAGE_ALIASES.get(stage, stage)
    if stage not in STAGE_ORDER:
        return []
    record = _fm.verified_foundation_records().get(foundation_id)
    if record is None:
        return []
    allowed = STAGE_ORDER[: STAGE_ORDER.index(stage) + 1]
    return [
        {**feature, "id": feature_id(foundation_id, feature["name"])}
        for feature in foundation_feature_blocks(record) if feature["stage"] in allowed
    ]


def iter_all_features() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(foundation_id, record, feature) for every printed feature of every verified Foundation."""
    return [
        (foundation_id, record, feature)
        for foundation_id, record in sorted(_fm.verified_foundation_records().items())
        for feature in foundation_feature_blocks(record)
    ]
