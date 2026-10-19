"""Foundation Feature blocks by stage, from the playable Foundations catalog (owner 2026-09-25).

A finished character's owner sheet carries ``foundation.mechanics.source_passives``
(numeric bonuses already applied at creation, see ``foundation_mechanics.py``) but
not the Foundation's other printed features, and combat never sees them either.
This module reads the same verified catalog records ``foundation_mechanics.py``
uses (``foundation_corpus_release`` + the pinned runtime registry) and returns
every printed feature block -- "## 4. Foundation Features", the resource's own
generation trigger under "## 3. Foundation Resource", and the Refined/Perfected
blocks under "## 5. Stage Progression" -- tagged with the stage it becomes
available at, for the typed mechanics authority and the combat compiler.
"""
from __future__ import annotations

import re
from typing import Any

from . import foundation_mechanics as _fm

STAGE_ORDER = ("Awakened", "Refined", "Perfected")

_FIELD_RE = re.compile(r"^\*\*([^*]+):\*\* (.+)$", re.MULTILINE)


def _slug(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def feature_id(foundation_id: str, name: str) -> str:
    return f"foundation.{foundation_id}.{_slug(name)}"


def _stage_tier(available_at: str | None) -> str:
    text = (available_at or "").casefold()
    if "perfected" in text:
        return "Perfected"
    if "refined" in text:
        return "Refined"
    return "Awakened"  # "Awakened or higher", "Common Expression or higher", or unstated.


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
    the Refined/Perfected subsections there ever add genuinely new blocks.
    """
    surfaces = record["semantic_surfaces"]
    seen: dict[str, dict[str, Any]] = {}
    for name, fields in [*_blocks(surfaces["features"]), *_resource_generation_blocks(surfaces["resource"])]:
        seen.setdefault(name, {"name": name, "stage": _stage_tier(fields.get("Available At")), "fields": fields})
    for stage_chunk in re.split(r"^### ", surfaces["progression"], flags=re.MULTILINE)[1:]:
        header, _, rest = stage_chunk.partition("\n")
        stage = header.strip()
        if stage not in ("Refined", "Perfected"):
            continue
        for name, fields in _blocks(rest):
            seen.setdefault(name, {"name": name, "stage": stage, "fields": fields})
    return list(seen.values())


def features_for_stage(foundation_id: str, stage: str | None) -> list[dict[str, Any]]:
    """Every feature available at or below ``stage`` (cumulative), catalog order.

    An unrecognized or unstable stage (e.g. a Foundation's alternate "Unstable"
    initial state) grants none, matching how the initial-mechanics layer already
    treats an unstable Foundation as unable to claim its stable benefits.
    """
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
