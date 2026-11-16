"""Incapacitating conditions end every current and held Concentration copy."""

import pytest

from combat import concentration, ext
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_auto_docket import ROOT
from tests.h1_support import sheet
from tests.test_multi_concentration import _engine


@pytest.mark.parametrize("name", ["incapacitated", "stunned", "paralyzed", "petrified", "unconscious"])
def test_condition_applied_ends_current_and_held_concentration(name):
    engine, actor = _engine(5)
    engine._start_concentration(actor, "test:older-technique")
    engine._start_concentration(actor, "test:current-technique")
    assert len(concentration.sources(actor)) == 2
    # The condition is on the creature when its CONDITION_APPLIED event fires, as in a real table action.
    engine._apply_condition(actor, f"condition:typed.{name}", "test:attacker", "test:attacker", expires_on="UNTIL_REMOVED")

    ext.run("event", engine, "CONDITION_APPLIED", {
        "actor_id": "test:attacker", "target_ids": (actor.entity_id,),
        "payload": {"condition_id": f"condition:typed.{name}"},
    })

    assert concentration.sources(actor) == []
    endings = [event for event in engine.events if event.event_type == "CONCENTRATION_ENDED"]
    assert [event.payload["reason"] for event in endings] == ["INCAPACITATED", "INCAPACITATED"]


def test_unrelated_condition_does_not_end_concentration():
    engine, actor = _engine(5)
    engine._start_concentration(actor, "test:technique")

    ext.run("event", engine, "CONDITION_APPLIED", {
        "actor_id": "test:attacker", "target_ids": (actor.entity_id,),
        "payload": {"condition_id": "condition:typed.prone"},
    })

    assert concentration.sources(actor) == ["test:technique"]


def test_stun_ends_concentration_in_committed_table_after_reload_and_replay(tmp_path):
    ids = ["actor:factory.stunner", "actor:factory.ally", "actor:factory.burner", "actor:factory.foe"]
    docs = [sheet(["TAL_IRON_FIST_ONE_INCH_HEAVENQUAKE"], cl=15), sheet([], cl=15),
            sheet(["FIRE_TAL_BURNING_WEAPON"], cl=15), sheet([], cl=15)]
    bundles = [compile_character(doc, actor_id=actor_id) for doc, actor_id in zip(docs, ids)]
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    match_id = service._finish_factory_match(
        bundles, ids, {actor_id: ("team:a" if index < 2 else "team:b") for index, actor_id in enumerate(ids)},
        dict(zip(ids, [{"x": 3, "y": 6}, {"x": 3, "y": 5}, {"x": 4, "y": 6}, {"x": 4, "y": 5}])),
        service.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], ids[:2], ids[2:],
        control_modes={actor_id: "MANUAL" for actor_id in ids}, match_seed="H43-CONCENTRATION-21",
        display_name="Stun Concentration regression", maximum_rounds=4,
    )["match_id"]

    def commit(source, target=None):
        state = table.state(match_id)
        menu = state["menu"]
        if source == "end":
            candidate_id = menu["end_turn"]
        else:
            groups = [group for group in menu["actions"] if source in group["source_definition_id"]]
            options = [option for group in groups for option in group["options"]
                       if target is None or target in option["target_ids"]]
            assert options, f"no legal option for {source} targeting {target}"
            candidate_id = sorted(options, key=lambda item: -(item.get("expected_damage") or 0))[0]["candidate_id"]
        result = table.act(match_id, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"])
        answers = []
        while result["status"] == "REACTION_REQUIRED":
            prompt = result["reaction"]
            choice = prompt.get("choice") or {}
            answer = {**prompt["context"], "selection": "DECLINE"}
            if choice and not choice.get("allow_decline", True):
                answer.update(selection="USE", option_ids=[o["id"] for o in choice["options"][:choice.get("minimum", 1)]])
            answers.append(answer)
            result = table.act(match_id, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        assert result["status"] == "COMMITTED"
        return result

    while table.state(match_id)["menu"]["actor_id"] != ids[2]:
        commit("end")
    commit("FIRE_TAL_BURNING_WEAPON")
    while table.state(match_id)["menu"]["actor_id"] != ids[0]:
        commit("end")
    commit("TAL_IRON_FIST_ONE_INCH_HEAVENQUAKE", ids[2])

    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    target = reloaded.engine.state.actors[ids[2]]
    assert any(row.condition_id == "condition:typed.stunned" for row in target.conditions.values())
    assert concentration.sources(target) == []
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["status"] == "PASS"
