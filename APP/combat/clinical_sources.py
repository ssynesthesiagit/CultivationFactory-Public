"""Explicit clinical sources for owner-authored encounters.

Public owner/GM input: create_match(combat, source_file=..., **match_setup).
The local source file must be a private regular file owned by the server user.
This is a trusted encounter-authoring API, never an actor/AI intent parameter.
Like arena authoring, the GM supplies world facts; no condition name, damage,
team, creature type or receipt implies a clinical classification.

Coagulate uses ordinary_bleeding_instances. Future clinical consumers can reuse
the same exact-source contract without changing existing/native conditions.
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


def create_match(combat, *, source_file, typed_bundles, **setup):
    """Create a native match from a private, locally authorized GM source file.

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
    roster = setup.get("roster_setup") or {}
    primary_actor_ids = roster.get("primary_actor_ids")
    if not primary_actor_ids:
        raise ValueError("Clinical source setup requires roster_setup.primary_actor_ids.")
    actors = set(primary_actor_ids)
    rows = validate_sources(rows, actors)
    if not {row["subject"] for row in rows} <= {b["actor_id"] for b in bundles}:
        raise ValueError("Clinical subjects need a supplied typed bundle.")
    for bundle in bundles:
        if SETUP in bundle:
            raise ValueError("Clinical source setup is already sealed.")
        bundle[SETUP] = [r for r in rows if r["subject"] == bundle["actor_id"]]
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    return combat.persistence.create_match(typed_bundles=tuple(bundles), **setup)