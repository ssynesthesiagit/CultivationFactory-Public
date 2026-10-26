"""Source-qualified Background-Origin roll edges, separate from Foundation Origins.

Only exact validated acquisitions seal ownership. Check hazards and save
categories are authored mechanical context, never inferred from names, model
text or other creatures' hidden state. Missing context grants no benefit.
Information, initiative, surprise, object handling and long-rest rerolls are
not implemented by these roll-mode providers.
"""
from . import hook
from .passive_rows import row_of
from ..origin_acquisition import PREFIX, selected_origin

BLOCK = "background_origin"
HASHES = {
    "street_hardened": "1da1633fff2876a74e1ac5b4cccdd0645d0b5baf0e7e3332ded0473a3fb3fadc",
    "hunger_memory": "da62fa2982413f80dba7ba09454e5bd89b79c913497a9b7fba1207f6b5589b85",
    "no_one_saves_you": "7ea6952fd668f920fd1eb097630b1ef41caed62910cf33c68fd17a3556e1097d",
    "quick_hands": "b2072a4fa676aeb8e40b15551cf23cdf43026eaea43eef7f9aebd37f08d4b3b7",
}
DEPRIVATION = frozenset({"hunger", "thirst", "exposure", "forced_march", "sleep_deprivation", "ordinary_deprivation"})
PLACES = frozenset("place:" + place for place in ("settlement", "ruin", "market", "alley", "dock", "slum", "crowded_public_space"))
THREATS = frozenset({"ordinary_ambush", "pickpocket", "tailing", "lookout_signal", "sudden_street_violence"})
PRISON = frozenset({"weak_restraints", "careless_guards", "unsecured_doors", "loose_bindings", "bad_prison_habits"})


def acquisition(sheet):
    row = selected_origin(sheet)
    if row and row["section_sha256"] == HASHES.get(row["feature_id"].removeprefix(PREFIX)):
        return row


@hook("compile_acquisition_ids")
def acquisition_ids(owner_sheet):
    row = acquisition(owner_sheet)
    return [row["feature_id"]] if row else None


@hook("compile_passives")
def seal_owned(passives, info):
    row = acquisition(info.get("owner_sheet") or {})
    if row and row["feature_id"] in info["owned_ids"]:
        return [*passives, {**row, "block": BLOCK, "kind": row["feature_id"].removeprefix(PREFIX)}]
    return passives


def owns(engine, actor, kind):
    row = row_of(engine, actor.entity_id, BLOCK, kind)
    return row is not None and row.get("section_sha256") == HASHES.get(kind)


@hook("ability_check_hazards")
def check_edge(engine, actor, ability, skill, hazards):
    facts = set(hazards)
    if owns(engine, actor, "hunger_memory") and facts & DEPRIVATION:
        return "ADVANTAGE"
    if (owns(engine, actor, "street_hardened") and ability == "WIS" and skill == "Perception"
            and facts & PLACES and facts & THREATS):
        return "ADVANTAGE"
    if owns(engine, actor, "no_one_saves_you") and "notice" in facts and facts & PRISON:
        return "ADVANTAGE"
    if owns(engine, actor, "quick_hands") and {"hide_on_body", "hand_sized_object"} <= facts:
        return "ADVANTAGE"


@hook("save")
def deprivation_save(ctx, subject, ability, named):
    if owns(ctx.engine, subject, "hunger_memory") and set(named or ()) & {"category:" + value for value in DEPRIVATION}:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
