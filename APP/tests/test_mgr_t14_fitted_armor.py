"""Source-qualified Equipment preparation through native service and cold fights."""
from copy import deepcopy
from importlib import import_module

import pytest

from combat.gate5_service import CombatService
from combat.factory_compiler import compile_character
from combat.tabletop_service import TabletopService
from combat.ext.armor_subject import fitted_ready
from tests.h1_support import ROOT

support = import_module("tests.test_review_sw-equipment")
# A real project identity is required by the saved-loadout and public APIs.
ACTOR = "actor:factory.00000000-0000-4000-8000-000000000014"
PROJECT = ACTOR.removeprefix("actor:factory.")
LAMELLAR = "tianxia.mortal.armor.lacquered_lamellar"
LEATHER = "tianxia.mortal.armor.lacquered_leather"


def sheet(talents=(), *, proficiency=("medium", "light")):
    doc = deepcopy(support._sheet(list(talents), items=[
        {"item_id": LAMELLAR, "name": "Lamellar", "quantity": 1},
        {"item_id": LEATHER, "name": "Leather", "quantity": 1}]))
    doc["proficiencies"] = {"armor": list(proficiency)}
    return doc


def command(root, doc, operation="inspect", **parameters):
    """The service reads a fixture source sheet; callers supply no proficiency."""
    from combat.preparation import PreparationStore
    service = CombatService(ROOT, root)
    service._factory_owner_sheet = lambda project: deepcopy(doc)
    revision = PreparationStore(root).read(ACTOR)["revision"]
    return service.character_preparation(PROJECT, operation, parameters=parameters, expected_revision=revision)


def fight(root, doc, *, prepare=None, attacker_position=(8, 6), defender_position=(3, 6),
          attacker_sheet=None, extra=(), arena=None):
    bundles = [compile_character(attacker_sheet or support._sheet([]), actor_id=support.ATTACKER),
               compile_character(doc, actor_id=ACTOR, reaction_plan={"mode": "ask", "ask": True})]
    bundles.extend(b for b, position in extra)
    if prepare:
        for b in bundles:
            prepare(b)
    service = CombatService(ROOT, root)
    ids = [b["actor_id"] for b in bundles]
    opponents = [i for i in ids if i != ACTOR]
    mid = service._finish_factory_match(bundles, ids,
        {i: "team:factory" if i == ACTOR else "team:opponents" for i in ids},
        {support.ATTACKER: {"x": attacker_position[0], "y": attacker_position[1]},
         ACTOR: {"x": defender_position[0], "y": defender_position[1]},
         **{b["actor_id"]: {"x": p[0], "y": p[1]} for b, p in extra}},
        arena or service.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ACTOR], opponents,
        control_modes={i: "MANUAL" for i in ids},
        match_seed=f"MGR-T14:{len(service.persistence.list_matches())}", maximum_rounds=6,
        display_name="Fitted armor regression")["match_id"]
    return service, TabletopService(service, root), mid


def fit(root, doc, key=LAMELLAR):
    command(root, doc, "armor.fit.start", item_key=key)
    return command(root, doc, "time.advance", seconds=600, observation="fitting")


def prone_action(bundle):
    """Native Lie down fixture for this packet's published factory actor ID."""
    from tests.test_a2_equipment import PREPARE
    if bundle["actor_id"] != ACTOR:
        return
    support._bundle_action(bundle, PREPARE, "Lie down",
        {"typed": {"numbers": {}, "riders": [], "duration": {"kind": "instant"},
                   "effects": [{"type": "condition", "condition": "prone", "applies_to": "self"}]}},
        target_kind="SELF", range_ft=None)
    support._seal(bundle)


def test_designation_requires_ten_minutes_and_source_proficiency(tmp_path):
    doc = sheet()
    assert command(tmp_path, doc)["armor"]["fitted_key"] == ""
    command(tmp_path, doc, "armor.fit.start", item_key=LAMELLAR)
    assert command(tmp_path, doc, "time.advance", seconds=600)["armor"]["ready"] == 0
    assert command(tmp_path, doc, "time.advance", seconds=599, observation="fitting")["armor"]["ready"] == 0
    assert command(tmp_path, doc, "time.advance", seconds=1, observation="fitting")["armor"]["fitted_key"] == LAMELLAR
    denied = sheet(proficiency=())
    with pytest.raises(ValueError, match="proficiency"):
        command(tmp_path, denied, "armor.fit.start", item_key=LAMELLAR)
    with pytest.raises(ValueError, match="source-qualified"):
        command(tmp_path, doc, "armor.fit.start", item_key="imaginary-suit")
    service, table, mid = fight(tmp_path, doc)
    engine = support._reload(tmp_path, mid)
    assert fitted_ready(engine, engine.state.actors[ACTOR])
    assert table.state(mid)["match_id"] == mid


def test_designation_single_suit_is_separate_from_worn_suit(tmp_path):
    doc = sheet()
    fit(tmp_path, doc)
    command(tmp_path, doc, "armor.fit.start", item_key=LEATHER)
    state = command(tmp_path, doc, "time.advance", seconds=599, observation="fitting")
    assert state["armor"]["fitted_key"] == LAMELLAR
    state = command(tmp_path, doc, "time.advance", seconds=1, observation="fitting")
    assert state["armor"]["fitted_key"] == LEATHER
    _, _, mid = fight(tmp_path, doc)
    engine = support._reload(tmp_path, mid)
    assert not fitted_ready(engine, engine.state.actors[ACTOR])
    assert engine.typed_bundle_documents[1]["armor_subject"]["fitted_key"] == LEATHER


@pytest.mark.parametrize("reason", ["lost_proficiency", "destroyed"])
def test_designation_revocation_survives_service_restart_and_fight_reload(tmp_path, reason):
    doc = sheet()
    fit(tmp_path, doc)
    if reason == "lost_proficiency":
        doc["proficiencies"]["armor"] = ["light"]
    else:
        command(tmp_path, doc, "armor.destroy", item_key=LAMELLAR)
    assert command(tmp_path, doc)["armor"]["fitted_key"] == ""
    if reason == "destroyed":
        with pytest.raises(ValueError, match="Destroyed armor"):
            fight(tmp_path, doc)
        doc["equipment"][0]["starting_kit"]["items"] = [i for i in doc["equipment"][0]["starting_kit"]["items"]
                                                       if i["item_id"] != LAMELLAR]
    _, _, mid = fight(tmp_path, doc)
    engine = support._reload(tmp_path, mid)
    assert not fitted_ready(engine, engine.state.actors[ACTOR])
    if reason == "lost_proficiency":
        doc["proficiencies"]["armor"].append("medium")
        assert command(tmp_path, doc)["armor"]["fitted_key"] == ""


def test_designation_during_actual_long_rest_not_starting_a_new_fight(tmp_path):
    doc = sheet(["sleep_in_armor"])
    command(tmp_path, doc, "rest.start", kind="long_rest")
    command(tmp_path, doc, "armor.fit.start", item_key=LAMELLAR)
    assert command(tmp_path, doc, "time.advance", seconds=28799, observation="sleep")["armor"]["ready"] == 0
    assert command(tmp_path, doc, "time.advance", seconds=1, observation="sleep")["armor"]["ready"] == 1
    _, _, mid = fight(tmp_path, doc)
    engine = support._reload(tmp_path, mid)
    assert fitted_ready(engine, engine.state.actors[ACTOR])
