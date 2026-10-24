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
            for row in features if row["canonical_id"] in contracts()]


def resolve(features, selections, *, required=True):
    """The recorded picks for these features. A new level must answer every feature (required=True). A level already
    in a character's history may have no pick (it was levelled before the choice existed): required=False records
    only the picks it has, and the compiler then reads the feature as unchosen. Unknown picks are rejected either way."""
    offered = menu(features)
    keys = {r["feature_id"] for r in offered}
    if (set(selections) != keys) if required else not set(selections) <= keys:
        raise FoundryError("TABLETOP_LEVEL_NOT_LEGAL", "Choose each feature's required build option before leveling up.", status_code=409)
    out = {}
    for row in offered:
        if row["feature_id"] not in selections:
            continue
        option = next((r for r in row["options"] if r["id"] == selections[row["feature_id"]]), None)
        if option is None:
            raise FoundryError("TABLETOP_LEVEL_NOT_LEGAL", "Choose an offered option for " + row["name"] + ".", status_code=409)
        out[row["feature_id"]] = {"choice": option["id"], **copy.deepcopy(option["grants"])}
    return out
