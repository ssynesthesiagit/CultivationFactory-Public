"""MGR-T14-ling-trad-nightmare-touch-1: WHOLE Nightmare Touch verification.

Exact ID: tianxia.tradition.spirit.dream_eater.feature.nightmare_touch (CL6).
Native producers: generic typed compile (Action, 3 Resonance, 30ft, Wisdom save,
4d8+Wis psychic fail / half success, Nightmare Scar) + APP/combat/ext/dream_eater.py
(touch_morsel, touch_waking, scar_first_save, _feed_on_resistance, range gate,
nightmare_sleep_damaged) + spirit_awakening.py (spiritual_pressure, Soul Gaze).

Each test runs real compiled acquisition -> engine intent -> committed state.
A companion reload test commits through a table session and cold-reloads.
"""
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.c8"
FOE = AN
DE = "tianxia.tradition.spirit.dream_eater.feature."
DE_ALL = [DE + k for k in ("dream_walker", "nightmare_touch", "stolen_dreams", "sleeping_curse", "dream_eater_ascension")]
MORSEL = "resource:named.dream_morsel"
MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
PRESSURE = "condition:typed.spirit_awakening_pressure."
@lru_cache(maxsize=1)
def authority():
    return json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())


def sheet(ids, *, cl=18, pb=6, wis=4, dc=17, resonance=60):
    mods = {"STR": 1, "DEX": 2, "CON": 2, "INT": 1, "WIS": wis, "CHA": 1}
    return {
        "identity": {"proficiency_bonus": pb, "cultivation_level": cl, "path": "Spirit Awakening", "key_ability": "WIS"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 10 + 2 * m, "modifier": m} for a, m in mods.items()],
            "primary_resource": {"name": "Resonance", "maximum": resonance}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 90}, "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 9},
        "path_and_subpath": {"path_record_ids": [], "path_feature_record_ids": list(ids)},
    }


def bundle(ids, actor_id=ME, **kw):
    return compile_character(sheet(ids, **kw), actor_id=actor_id, typed_authority=authority())


def fight(ids, *, foe_at=(4, 6), seed="NT1", **kw):
    from combat.gate4_engine import Gate4ControllerEngine
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle(ids, **kw),),
                                   roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": foe_at[0], "y": foe_at[1]}}})
    turn(engine, ME)
    return engine


def turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    return actor


def legal(engine):
    return {c.display_name for c in engine.legal_candidates()}


def candidates(engine, name, target=None):
    return [c for c in engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ()))]


def use(engine, name, target=None, actor_id=ME):
    matches = candidates(engine, name, target)
    assert matches, f"{name!r} is not legal; legal: {sorted(legal(engine))}"
    candidate = matches[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"nt1-{name}-{len(engine.events)}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor_id,
                                       target_ids=(target,) if target else (candidate.target_ids or ()), destination=candidate.destination))
    return engine.events[before:]


def payloads(events, kind):
    return [getattr(e, "payload", None) or {} for e in events if e.event_type == kind]


def held(actor, condition_id, source_actor=None):
    return [c for c in actor.conditions.values() if c.condition_id == condition_id and (source_actor is None or c.source_actor_id == source_actor)]


def mark_resonance(engine, subject_id, owner=ME):
    engine._apply_condition(engine.state.actors[subject_id], typed_executor.mark_condition_id("Resonance", owner), "test", owner,
                            expires_on="UNTIL_REMOVED")


def scar(engine, subject_id, owner=ME):
    engine._apply_condition(engine.state.actors[subject_id], typed_executor.mark_condition_id("Nightmare Scar", owner), "test", owner,
                            expires_on="UNTIL_REMOVED")


def put_to_sleep(engine, subject_id, owner=ME):
    engine._apply_condition(engine.state.actors[subject_id], "condition:typed.unconscious", "test-sleep", owner,
                            expires_on="UNTIL_REMOVED", data={"label": "sleep"})


def answers(engine, table):
    from combat.gate2_runtime_models import ReactionDecision

    def provider(request):
        spec = request.get("extension_choice")
        if spec is None:
            return None, None
        source = request["reaction_source_id"]
        key = next((k for k in table if source.endswith(k)), None)
        if key is None:
            pick = (spec.get("preferred_option_ids") or spec["option_ids"])[:max(1, spec["minimum_selections"])]
        else:
            pick = table[key]
            pick = pick(list(spec["option_ids"])) if callable(pick) else pick
        base = {k: request[k] for k in ("checkpoint", "reactor_id", "reaction_source_id")}
        if pick is None:
            return ReactionDecision(**base, selection="DECLINE", option_ids=()), None
        return ReactionDecision(**base, selection="USE", option_ids=tuple(pick)), None

    engine.set_reaction_provider(provider)


def test_touch_compiles_once_with_cost_and_gate():
    engine = fight([*DE_ALL, MIND_SPIKE], dc=40, foe_at=(7, 6))  # 20 feet, awake, unmarked
    assert len(candidates(engine, "Nightmare Touch", FOE)) == 0  # beyond Touch, needs sleep or mark
    assert "Nightmare Touch" not in legal(engine)
    mark_resonance(engine, FOE)
    assert len(candidates(engine, "Nightmare Touch", FOE)) == 1  # exactly one compiled action, no duplicate
    mine = [a for a in engine.action_catalog.values() if getattr(a, "display_name", None) == "Nightmare Touch"]
    assert len(mine) == 1
    assert list(mine[0].costs) == [["resource:core.resonance", 3]] or tuple(mine[0].costs) == (("resource:core.resonance", 3),)
    assert mine[0].range_ft == 30


def test_touch_in_touch_range_needs_no_mark():
    engine = fight([*DE_ALL, MIND_SPIKE], dc=40, foe_at=(4, 6))  # 5 feet: Touch
    assert len(candidates(engine, "Nightmare Touch", FOE)) == 1


def test_failed_save_scars_damages_and_gives_a_morsel_from_sleep():
    engine = fight([*DE_ALL, MIND_SPIKE], dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    put_to_sleep(engine, FOE)
    answers(engine, {"dream_eater.keep_sleep": None})  # decline: it wakes after the damage
    before = me.resources["resource:core.resonance"]
    use(engine, "Nightmare Touch", FOE)
    assert me.resources["resource:core.resonance"] == before - 3
    assert typed_executor.bears_mark(foe, ME, "Nightmare Scar")
    dealt = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and FOE in (e.target_ids or ())]
    assert dealt and all(str((e.payload or {}).get("damage_type")).lower() == "psychic" for e in dealt)
    assert 8 <= sum(int((e.payload or {}).get("hp_damage") or 0) for e in dealt) <= 36  # 4d8 + Wis mod
    assert me.resources[MORSEL] == 1  # asleep (pre-save) hostile: one Morsel, subject to the limit
    assert not any(c.condition_id == "condition:typed.unconscious" for c in foe.conditions.values())  # wakes


def test_ai_keeps_sleep_when_it_holds_a_morsel_and_other_damage_wakes():
    engine = fight([*DE_ALL, MIND_SPIKE], dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    put_to_sleep(engine, FOE)
    engine._gain_resource(me, MORSEL, 1, "test")
    use(engine, "Nightmare Touch", FOE)  # AI default takes preferred: keep asleep
    assert me.resources[MORSEL] == 1  # spent 1 to keep, gained 1 from the sleeping hostile: net held 1
    assert held(foe, "condition:typed.nightmare_sleep", ME)
    assert any(c.condition_id == "condition:typed.unconscious" for c in foe.conditions.values())
    me.action_available = True
    use(engine, "Mind Spike", FOE)  # damage from another source wakes
    assert not held(foe, "condition:typed.nightmare_sleep", ME)
    assert not any(c.condition_id == "condition:typed.unconscious" for c in foe.conditions.values())


def test_successful_save_is_half_damage_with_no_scar_and_no_feed():
    engine = fight([*DE_ALL, MIND_SPIKE], dc=-40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    use(engine, "Nightmare Touch", FOE)
    assert not typed_executor.bears_mark(foe, ME, "Nightmare Scar")
    dealt = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and FOE in (e.target_ids or ())]
    assert dealt  # half damage still lands
    assert me.resources[MORSEL] == 0  # unscarred success: no Morsel, no Feed spending offered
    assert not [c for c in foe.conditions.values() if c.condition_id.startswith(PRESSURE)]


def test_feed_on_resistance_pressures_and_preserves_the_scar():
    engine = fight([*DE_ALL, MIND_SPIKE], dc=-40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    scar(engine, FOE)
    engine._gain_resource(me, MORSEL, 1, "test")
    answers(engine, {"dream_eater.feed_on_resistance": ("feed",)})
    events = use(engine, "Nightmare Touch", FOE)  # meaningful hostile succeeds while already scarred
    assert me.resources[MORSEL] == 1  # gained pre-save (already scarred), spent 1 to feed
    assert [c for c in foe.conditions.values() if c.condition_id.startswith(PRESSURE)]  # ordinary Spiritual Pressure
    me.action_available = True
    events2 = use(engine, "Nightmare Touch", FOE)
    [save] = [p for p in payloads(events2, "SAVE_ROLLED") if p.get("actor_id") == FOE]
    assert len(save.get("dice") or ()) == 2  # the Scar's first-save Disadvantage was NOT expended


def test_decline_leaves_the_spent_scar_spent():
    engine = fight([*DE_ALL, MIND_SPIKE], dc=-40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    scar(engine, FOE)
    engine._gain_resource(me, MORSEL, 1, "test")
    answers(engine, {"dream_eater.feed_on_resistance": None})  # decline
    use(engine, "Nightmare Touch", FOE)
    assert me.resources[MORSEL] == 2  # gained pre-save (already scarred), unspent on decline
    me.action_available = True
    events2 = use(engine, "Nightmare Touch", FOE)
    [save] = [p for p in payloads(events2, "SAVE_ROLLED") if p.get("actor_id") == FOE]
    assert len(save.get("dice") or ()) == 1  # the first-save Disadvantage was expended by the success


def test_touch_commits_through_a_table_session_and_cold_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="NT1-RELOAD", typed_bundles=(bundle([*DE_ALL, MIND_SPIKE], dc=40),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"nt1-{name}-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=(target,) if target else candidate.target_ids,
                                                       destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Nightmare Touch", FOE)  # Touch range needs no mark; the failed save scars (no Morsel: the Scar is new, not pre-existing)
    assert session.engine.state.actors[ME].resources["resource:core.resonance"] == 57
    reloaded = persistence.load_match(session.match_id)
    foe = reloaded.engine.state.actors[FOE]
    assert typed_executor.bears_mark(foe, ME, "Nightmare Scar")
    assert foe.current_hp < foe.maximum_hp
    assert reloaded.verify()["status"] == "PASS"


def test_manual_player_is_asked_before_sleep_is_kept():
    import tempfile
    from combat.gate5_service import CombatService, _ReactionRequired
    engine = fight([*DE_ALL, MIND_SPIKE], dc=40, foe_at=(6, 6))
    me = engine.state.actors[ME]
    put_to_sleep(engine, FOE)
    engine._gain_resource(me, MORSEL, 1, "test")
    with tempfile.TemporaryDirectory(prefix='cf-nt1-ask-', dir='/var/tmp') as scratch:
        service = CombatService(ROOT, Path(scratch))
        session = service.persistence.create_match(match_seed="NT1-ASK", typed_bundles=())
        session.engine = engine
        candidate = next(c for c in engine.legal_candidates() if c.display_name == "Nightmare Touch" and FOE in (c.target_ids or ()))
        intent = ActionIntent(intent_id="nt1-ask", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                              state_version=candidate.state_version, actor_id=ME, target_ids=(FOE,), destination=candidate.destination)
        metadata = {"participant_control_modes": {ME: "MANUAL", **{a: "LOCAL_AUTO" for a in engine.state.actors if a != ME}}}
        try:
            service._run_preview(session, metadata, intent, ())
        except _ReactionRequired as paused:
            context = paused.value.context if hasattr(paused, "value") else paused.context
            assert "keep" in json.dumps(context.model_dump(mode="json") if hasattr(context, "model_dump") else context, default=str).lower()
            return
        pytest.fail("a manual player was not asked the keep-asleep choice")
