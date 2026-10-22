"""Explicit clinical sources for owner-authored encounters.

Public owner/GM input: attach_sources(typed_bundles, source_file=..., primary_actor_ids=...)
before the owner-side match is finished, so the sealed roster travels in the typed bundles.
The local source file must be a private regular file owned by the server user.
This is a trusted encounter-authoring API, never an actor/AI intent parameter.
Like arena authoring, the GM supplies world facts; no condition name, damage,
team, creature type or receipt implies a clinical classification.

Coagulate reads ordinary_bleeding_instances at resolution time from the sealed
engine.typed_bundle_documents. A Bleeding instance is ordinary only when a sealed
row names its source rule (rule_id), classifies it ordinary_bleeding, and lists the
caster as an authorized reader. Future clinical consumers can reuse this contract.
Absent explicit sources this module is inert. Source facts are sealed in typed
bundles for genesis/replay; only primitive strings/integers enter conditions.
"""
from __future__ import annotations

import copy
import json
import os
import stat
from pathlib import Path

from .canonical import canonical_sha256

SETUP = "clinical_sources_v1"
DATA = "clinical_source_v1"


def validate_sources(rows, actors):
    """Validate exact external instances and explicit authorized readers.

    An ordinary wound has no invented damage, severity, healing or timer.
    It persists until actually treated; 'other' sources are never treatable by
    Coagulate. Native timed sources retain their own engine expiry instead.
    """
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("Supply at most 100 clinical sources.")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
                "source_id", "rule_id", "subject", "label", "category", "readers"}:
            raise ValueError("Supply source_id, rule_id, subject, label, category and readers.")
        if not all(type(row[k]) is str and 0 < len(row[k].strip()) <= 240
                   for k in ("source_id", "rule_id", "subject", "label", "category")):
            raise ValueError("Clinical source identities and labels must be bounded nonempty text.")
        if row["source_id"] in seen or row["subject"] not in actors:
            raise ValueError("Clinical sources need distinct identities and a present subject.")
        seen.add(row["source_id"])
        if row["category"] not in {"ordinary_bleeding", "other"}:
            raise ValueError("Explicitly classify the source as ordinary_bleeding or other.")
        readers = row["readers"]
        if (not isinstance(readers, list) or not all(type(v) is str for v in readers)
                or len(readers) != len(set(readers)) or not set(readers) <= set(actors)):
            raise ValueError("Clinical readers must be distinct creatures in this encounter.")
    return copy.deepcopy(rows)


def attach_sources(typed_bundles, *, source_file, primary_actor_ids):
    """Seal a private GM source file into the supplied typed bundles and return them.

    Call only on the trusted server, not from a player route. O_NOFOLLOW and
    owner/mode checks prevent accepting shared/player-controlled source files.
    The file describes real scene sources, not successful treatment receipts.
    Native actions, payments, consent and choices remain normal table intents.
    """
    fd = os.open(Path(source_file), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 100_000):
            raise ValueError("Clinical input must be a private owner file of at most 100 KB.")
        with os.fdopen(fd, "r", closefd=False) as stream:
            rows = json.load(stream)
    finally:
        os.close(fd)
    bundles = copy.deepcopy(list(typed_bundles))
    if not primary_actor_ids:
        raise ValueError("Clinical source setup requires the encounter's primary_actor_ids.")
    rows = validate_sources(rows, set(primary_actor_ids))
    if not {row["subject"] for row in rows} <= {b["actor_id"] for b in bundles}:
        raise ValueError("Clinical subjects need a supplied typed bundle.")
    for bundle in bundles:
        if SETUP in bundle:
            raise ValueError("Clinical source setup is already sealed.")
        bundle[SETUP] = [r for r in rows if r["subject"] == bundle["actor_id"]]
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    return bundles


def ordinary_bleeding_instances(engine, holder, caster_id):
    """Map holder's Bleeding instances the caster may end to their clinical label.

    Pure read of the sealed roster. Missing rows, other categories and sources the
    caster may not read are never offered: no classification is inferred from the
    condition name, damage, team or a receipt.
    """
    rows = []
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == holder.entity_id:
            rows = bundle.get(SETUP) or []
            break
    labels = {}
    for instance_id, held in holder.conditions.items():
        if held.condition_id != "condition:typed.bleeding":
            continue
        for row in rows:
            if (row["category"] == "ordinary_bleeding" and row["rule_id"] == held.source_definition_id
                    and caster_id in row["readers"]):
                labels[instance_id] = row["label"]
                break
    return labels
