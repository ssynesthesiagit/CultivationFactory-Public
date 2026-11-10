"""Saved modifier clocks must be explicit."""
import json

import pytest

from combat.factory_compiler import apply_modifiers, compile_character
from combat.gate3_storage import TYPED_BUNDLES_FILE, load_typed_bundles
from combat.on_hit_data import walk_effect_containers
from tests.test_typed_structure import AUTHORITY, LASH, _mechanic
import copy
from combat.saved_fight_format import UnsupportedSavedFight
from tests.h1_support import sheet


def test_real_thread_weighted_knot_compiles_with_round_clock():
    """The actual once-per-round option must carry its clock into compiled attacks."""
    bundle = compile_character(sheet(['THREAD_BASE_THREADED_STRIKE']), actor_id='actor:test')
    effects = [effect for action in bundle['action_catalog']
               for effect in walk_effect_containers(action.get('parameters', {}).get('typed', {}))
               if effect.get('modifier_once') == 'THREAD_BASE_THREADED_STRIKE']
    assert effects
    assert all(effect.get('modifier_once_period') == 'round' for effect in effects)


def test_threaded_strike_off_turn_survives_table_round_and_reload(tmp_path, monkeypatch):
    """Exercise the compiled Weighted Knot on a real opportunity-attack turn."""
    from combat.effect_eligibility import modifier_gate
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, script
    from tests.test_lock2_persistence import act

    owner, foe = "actor:factory.round_owner", "actor:factory.round_foe"
    attacker = sheet(["THREAD_BASE_THREADED_STRIKE"], score=8)
    defender = sheet([], score=30)
    defender["ability_scores_and_statistics"]["armor_class"]["base_value"] = -50
    attacker["equipment"] = [{"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.dao", "quantity": 1}]}}]
    bundle = compile_character(attacker, actor_id=owner)
    enemy = compile_character(defender, actor_id=foe)
    variant = next(a for a in bundle["action_catalog"]
                   if a["display_name"] == "Opportunity Attack + Threaded Strike: Weighted Knot")
    effect = next(e for e in walk_effect_containers(variant["parameters"]["typed"])
                  if e.get("modifier_once") == "THREAD_BASE_THREADED_STRIKE")
    # Select the compiled variant as the opportunity profile; no gate or period
    # is manufactured. This isolates the clock from the separate OA choice UI.
    opportunity = next(r for r in bundle["typed_reactions"] if r.get("block") == "opportunity")
    opportunity["action_id"] = variant["source_definition_id"]
    original = Gate4ControllerEngine._resolve_attack_spec

    def hit(engine, *args, **kwargs):
        script(engine, [19, *([1] * 40)])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", hit)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(
        match_seed="ROUND-OFF-TURN", typed_bundles=(bundle, enemy),
        roster_setup={"primary_actor_ids": [owner, foe],
                      "team_by_actor": {owner: "team:a", foe: "team:b"},
                      "starting_positions": {owner: {"x": 5, "y": 5}, foe: {"x": 5, "y": 6}}})
    mid = session.match_id
    combat.set_controller_mode(mid, actor_id=owner, controller_mode="MANUAL")
    combat.set_controller_mode(mid, actor_id=foe, controller_mode="MANUAL")
    table = TabletopService(combat, tmp_path)
    engine = combat._load_session(mid).engine
    assert engine.state.round_number == 1 and engine.state.current_actor_id == foe
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind == "MOVE" and c.destination.x == 5 and c.destination.y == 7)
    state = table.state(mid)
    answers = []
    for _ in range(12):
        result = table.act(mid, candidate.candidate_id, candidate.decision_id,
                           candidate.state_version, state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        options = prompt.get("choice", {}).get("options", [])
        answers.append({**prompt["context"], "selection": "USE",
                        "option_ids": [options[0]["id"]] if options else []})
    else:
        pytest.fail("opportunity attack did not commit")
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.current_actor_id == foe
    assert modifier_gate(loaded.engine, loaded.engine.state.actors[owner], effect)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.round_number == 1 and loaded.engine.state.current_actor_id == owner
    assert modifier_gate(loaded.engine, loaded.engine.state.actors[owner], effect)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.round_number == 2 and loaded.engine.state.current_actor_id == foe
    assert not modifier_gate(loaded.engine, loaded.engine.state.actors[owner], effect)


def test_saved_modifier_requires_explicit_period(tmp_path):
    mechanics = {
        "LASH": AUTHORITY["mechanics"]["LASH"],
        "LIMITED": _mechanic("LIMITED", "Limited Current", "passive", [], {
            "targets": ["Water Lash"], "scope": "named", "when": "hit", "optional": False,
            "limit": "once_per_round", "effects": [{"type": "extra_damage", "flat": 2, "on_hit_bonus": None}]}),
    }
    built = {"LASH": {"action_id": "a:lash", "name": "Water Lash", "economy": "action",
        "target_kind": "HOSTILE_ENTITY", "range_ft": 30, "costs": [],
        "typed": {"effects": copy.deepcopy(LASH), "riders": [], "numbers": {"pb": 4}},
        "mechanic": mechanics["LASH"], "modifiers": []}}
    apply_modifiers(built, list(mechanics), mechanics, "qi", {"qi": 10})
    typed = built["LASH"]["typed"]
    effect = next(e for e in walk_effect_containers(typed) if e.get("modifier_once") == "LIMITED")
    assert effect["modifier_once_period"] == "round"
    bundle = {
        "actor_id": "actor:test",
        "actor_template": {
            "entity_id": "actor:test", "display_name": "Test", "team_id": "team:test",
            "primary_combatant": True, "armor_class": 10, "maximum_hp": 10,
            "speed_ft": 30, "initiative_bonus": 0, "dexterity_score": 10,
            "proficiency_bonus": 2, "saving_throws": {}, "resources": [],
            "action_ids": ["action:test"], "reaction_ids": [],
        },
        "action_catalog": [{
            "source_definition_id": "action:test", "display_name": "Test",
            "owner_id": "actor:test", "economy": "ACTION", "resolution_kind": "TYPED",
            "target_kind": "SELF", "parameters": {"typed": typed},
        }],
    }
    path = tmp_path / TYPED_BUNDLES_FILE
    path.write_text(json.dumps([bundle]))
    assert load_typed_bundles(tmp_path) == (bundle,)
    del effect["modifier_once_period"]
    path.write_text(json.dumps([bundle]))
    with pytest.raises(UnsupportedSavedFight) as caught:
        load_typed_bundles(tmp_path)
    assert isinstance(caught.value.__cause__, ValueError)
    assert "modifier_once_period" in str(caught.value.__cause__)
