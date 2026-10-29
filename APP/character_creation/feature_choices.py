"""Source-bound build choices shared by creation clients and table level acquisition.

This contract records acquisition decisions, not combat effects. Choices and
derived grants are authored in rules data; callers cannot supply derived values.
"""
import copy
import json
from functools import lru_cache
from pathlib import Path

from app.core import FoundryError


@lru_cache(maxsize=1)
def contracts():
    return json.loads((Path(__file__).resolve().parents[1] / "rules/feature_build_choices.json").read_text())


def menu(features):
    return [{"feature_id": row["canonical_id"], "name": row["display_name"], **copy.deepcopy(contracts()[row["canonical_id"]])}
            for row in features if row["canonical_id"] in contracts()
            and not contracts()[row["canonical_id"]].get("automatic")]


def creation_features(path_ids):
    """The CL1 Path features a new character gains, which are offered for a Defensive Discipline pick at creation."""
    from stage2.ability_changes import published_path_records

    records = published_path_records()
    return [{"canonical_id": row["canonical_id"], "display_name": row["display_name"]}
            for path in path_ids
            for row in records[path]["compatibility"]["factory"]["stage2_authority"]["progression_by_cl"]["1"]["features"]]


def creation_refusal(row):
    """The plain-words refusal for a Path feature a new character has not answered (finding 4)."""
    if any("defensive_discipline" in option["grants"] for option in row["options"]):
        return f"Choose your Defensive Discipline for {row['name']} before creating the character."
    return f"Choose the build option for {row['name']} before creating the character."


def resolve(features, selections, *, required=True, existing=None):
    """The recorded picks for these features. A new level must answer every feature (required=True). A level already
    in a character's history may have no pick (it was levelled before the choice existed): required=False records
    only the picks it has, and the compiler then reads the feature as unchosen. Unknown picks are rejected either way."""
    offered = menu(features)
    keys = {r["feature_id"] for r in offered}
    if (set(selections) != keys) if required else not set(selections) <= keys:
        raise FoundryError("TABLETOP_LEVEL_NOT_LEGAL", "Choose each feature's required build option before leveling up.", status_code=409)
    selected = []
    for row in offered:
        if row["feature_id"] not in selections:
            continue
        option = next((r for r in row["options"] if r["id"] == selections[row["feature_id"]]), None)
        if option is None:
            raise FoundryError("TABLETOP_LEVEL_NOT_LEGAL", "Choose an offered option for " + row["name"] + ".", status_code=409)
        selected.append((row, option))
    # Multiple choices from the same printed list are distinct choices, not repeatable picks.
    pools = {}
    for source_id, value in (existing or {}).items():
        contract = contracts().get(source_id)
        if not contract or not isinstance(value, dict):
            continue
        pool = tuple(sorted(r["id"] for r in contract["options"]))
        choice = str(value.get("choice") or "").lower()
        if choice and any("defensive_discipline" in r["grants"] for r in contract["options"]):
            pools.setdefault(pool, set()).add(choice)
    for row, option in selected:
        pool = tuple(sorted(r["id"] for r in row["options"]))
        if "defensive_discipline" in option["grants"]:
            if option["id"] in pools.setdefault(pool, set()):
                raise FoundryError("TABLETOP_LEVEL_NOT_LEGAL", "Choose a different Defensive Discipline for each choice.", status_code=409)
            pools[pool].add(option["id"])
    out = {}
    for row, option in selected:
        out[row["feature_id"]] = {"choice": option["id"], **copy.deepcopy(option["grants"])}
    return out
