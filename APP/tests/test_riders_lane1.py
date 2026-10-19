"""Rider lane 1 (owner 2026-09-29: "i want everything we can automated, keep going until its only the non-combat ones left"):
combat abilities whose core ran but whose printed GM lines ("riders") were shown to the GM.  Each test compiles a real
character, runs the newly automated line through the engine, and fails on the typing the authority carried before.

Overrides: authority/typed_mechanics/reviewed_final.d/{charge,elements,review_sw-lightning,riders_lane1}.json; plug-ins:
combat/ext/arcs.py, combat/ext/lightning_riders.py (feature blocks in combat/rules/feature_blocks.d/riders_lane1.json).
Attacks always hit (every foe has AC -50); a save is forced with the sheet's technique DC (50 fails, -40 succeeds).
"""

from pathlib import Path

import pytest

from combat import typed_executor as te
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, ConcentrationState
from combat.gate4_engine import Gate4ControllerEngine
from tests import test_auto_lane1 as L

ROOT = Path(__file__).resolve().parents[1]
ME = L.ME
F1, F2, F3, F4 = "actor:riders.f1", "actor:riders.f2", "actor:riders.f3", "actor:riders.f4"
PB = 4
LASH, GATHER = "TAL_LIGHTNING_LIGHTNING_LASH", "TAL_LIGHTNING_GATHER_CHARGE"


def _rider_engine(mid, *, dc=50, cl=17, foes=None, talents=()):
    sheet = L._sheet(mid, dc=dc, cl=cl)
    sheet["spheres_and_talents"]["learned_talent_record_ids"].extend(talents)
    return _engine(compile_character(sheet, actor_id=ME), foes or {F1: (7, 6), F2: (8, 7)})


def _rider_action(engine, mid):
    return next(action for action in engine.action_catalog.values()
                if (action.parameters.get("typed") or {}).get("source") == mid
                and not action.parameters.get("player_only"))


def _rider_use(engine, mid, *, aim=None):
    action = _rider_action(engine, mid)
    return _rider_use_action(engine, action, aim=aim)


def _rider_use_action(engine, action, *, aim=None):
    candidates = [c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id]
    candidate = next((c for c in candidates if (aim is None or c.destination == aim)
                      and (not c.target_ids or AN in c.target_ids or tuple(c.target_ids) == (ME,))), None)
    assert candidate is not None, (action.display_name, [(c.target_ids, c.destination) for c in candidates[:8]])
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="rider-use", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=tuple(candidate.target_ids or ()),
                                       destination=candidate.destination))
    return engine.events[before:]


BLACK_SUN = "TAL_DAEMONIC_CULTIVATION_BLACK_SUN_OVER_THE_DANTIAN"


@pytest.mark.parametrize("dc,resource", [(50, "resource:an_eui.stamina"),
                                          (50, "resource:core.qi"), (50, "resource:core.resonance"),
                                          (-40, "resource:core.qi")])
def test_black_sun_waits_for_one_positive_cp_or_stamina_spend(dc, resource):
    from combat.ext.daemonic_riders import BLACK_SUN_STATE

    engine = _rider_engine(BLACK_SUN, dc=dc)
    foe = engine.state.actors[AN]
    foe.maximum_hp = 200
    foe.current_hp = 200
    foe.resources[resource] = foe.resource_maximums[resource] = 10
    seen = _answers(engine, {"black_sun_damage": ["necrotic"]})
    hp = foe.current_hp
    _rider_use(engine, BLACK_SUN)
    assert foe.current_hp == hp  # a save arms the consequence; it does not deal it
    assert any(c.condition_id == BLACK_SUN_STATE for c in foe.conditions.values())
    assert any("Black Sun Over the Dantian" in str(r) and foe.display_name in str(r) for r in seen)
    engine._spend_resource(foe, resource, 0, "test:zero")
    foe.resources["resource:core.martial_focus"] = foe.resource_maximums["resource:core.martial_focus"] = 1
    engine._spend_resource(foe, "resource:core.martial_focus", 1, "test:focus")
    assert foe.current_hp == hp
    engine._spend_resource(foe, resource, 1, "test:spend")
    damage = hp - foe.current_hp
    assert damage > 0
    assert not any(c.condition_id == BLACK_SUN_STATE for c in foe.conditions.values())
    packets = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and AN in e.target_ids
               and e.source_definition_id.endswith(BLACK_SUN)]
    assert len(packets) == 1
    engine._spend_resource(foe, resource, 1, "test:second")
    assert hp - foe.current_hp == damage


@pytest.mark.parametrize("dc", [50, -40])
def test_black_sun_unspent_consequence_expires_on_the_casters_printed_edge(dc):
    from combat.ext.daemonic_riders import BLACK_SUN_STATE

    engine = _rider_engine(BLACK_SUN, dc=dc)
    foe = engine.state.actors[AN]
    _rider_use(engine, BLACK_SUN)
    engine.state.current_actor_id = AN
    engine._system_start_turn()
    assert any(c.condition_id == BLACK_SUN_STATE for c in foe.conditions.values())
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    assert any(c.condition_id == BLACK_SUN_STATE for c in foe.conditions.values()) == (dc == 50)
    if dc == 50:
        engine.end_turn()
    assert not any(c.condition_id == BLACK_SUN_STATE for c in foe.conditions.values())


@pytest.mark.parametrize("foe_hp", [60, 1])
def test_black_sun_state_survives_a_persistent_commit_reload_and_spend(tmp_path, foe_hp):
    from combat.ext.daemonic_riders import BLACK_SUN_STATE
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    foe_sheet = L._sheet(BLACK_SUN, cl=17, dc=50)
    foe_sheet["ability_scores_and_statistics"]["hit_points"]["maximum"] = foe_hp
    session = persistence.create_match(match_seed="BLACK-SUN-SAVED",
        typed_bundles=(compile_character(L._sheet(BLACK_SUN, cl=17, dc=50), actor_id=ME),
                       compile_character(foe_sheet, actor_id=F1)),
        roster_setup={"primary_actor_ids": [ME, F1], "team_by_actor": {ME: "team:a", F1: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, F1: {"x": 4, "y": 6}}})

    def submit(predicate):
        e = session.engine
        c = next(c for c in e.legal_candidates() if predicate(c))
        session.submit_intent(ActionIntent(intent_id=f"sun:{e.state.state_version}", decision_id=c.decision_id,
            candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
            target_ids=c.target_ids, destination=c.destination), primary_decision_record=None, reaction_provider=None)

    while session.engine.state.current_actor_id != ME:
        submit(lambda c: c.kind == "END_TURN")
    action_id = _rider_action(session.engine, BLACK_SUN).source_definition_id
    submit(lambda c: c.source_definition_id == action_id and F1 in c.target_ids)
    saved = [c.model_dump(mode="json") for c in session.engine.state.actors[F1].conditions.values()
             if c.condition_id == BLACK_SUN_STATE]
    assert saved
    session = persistence.load_match(session.match_id)
    assert saved == [c.model_dump(mode="json") for c in session.engine.state.actors[F1].conditions.values()
                     if c.condition_id == BLACK_SUN_STATE]
    while session.engine.state.current_actor_id != F1:
        submit(lambda c: c.kind == "END_TURN")
    hp = session.engine.state.actors[F1].current_hp
    submit(lambda c: c.source_definition_id in session.engine.action_catalog and
           (session.engine.action_catalog[c.source_definition_id].parameters.get("typed") or {}).get("source") == BLACK_SUN)
    assert session.engine.state.actors[F1].current_hp < hp
    assert any(e.event_type == "DAMAGE_COMMITTED" and F1 in e.target_ids
               and e.source_definition_id.endswith(BLACK_SUN) for e in session.engine.events)
    session = persistence.load_match(session.match_id)
    assert not any(c.condition_id == BLACK_SUN_STATE for c in session.engine.state.actors[F1].conditions.values())
    assert session.verify()["status"] == "PASS"


@pytest.mark.parametrize("mid,essence,healing", [
    ("TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH", 1, 0),
    ("TAL_DAEMONIC_CULTIVATION_WORLD_DEVOURING_MAW", 2, 17),
])
def test_daemonic_defeat_pays_only_for_the_creature_this_activation_reduces_to_zero(mid, essence, healing):
    engine = _rider_engine(mid)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.current_hp = 10
    foe.current_hp = 1
    pool = "resource:named.devoured_essence"
    me.resources[pool] = 0
    me.reaction_available = False  # isolate the talent's reward from the separate Devour Essence reaction
    # (rider lane C13: Devour Essence is the Bonus Action on your own turn now -- combat/ext/devour_essence.py -- so isolate it by its row)
    engine.typed_passive_rows[ME] = [row for row in engine.typed_passive_rows.get(ME, []) if row.get("block") != "devour_essence"]
    # Owner 2026-10-01 friendly fire (LUNA27): the breather stands in its own
    # "Creatures in the cone" and saves too. Immunity to the breath's damage
    # isolates the payout and healing checks from that self-damage.
    from combat.typed_executor import Context, run_effects
    action = _rider_action(engine, mid)
    run_effects(Context(engine, me, action, None, action.parameters["typed"], [], None, {}),
                [{"type": "immunity", "applies_to": "self", "damage_types": ["NECROTIC", "POISON"]}])
    hp = me.current_hp
    _rider_use(engine, mid, aim=foe.position)
    fallen = sum(actor.current_hp == 0 for who, actor in engine.state.actors.items() if who != ME)
    assert fallen >= 1
    assert me.resources[pool] == essence * fallen
    assert me.current_hp == min(me.maximum_hp, hp + healing * fallen)


def test_thousand_mouth_saves_use_each_targets_preexisting_state_and_two_defeats_pay_corruption():
    mid = "TAL_DAEMONIC_CULTIVATION_THOUSAND_MOUTH_DEVOURING_ART"
    engine = _rider_engine(mid)
    me = engine.state.actors[ME]
    me.resources["resource:named.corruption"] = 0
    me.resource_maximums["resource:named.corruption"] = 10
    engine.state.actors[AN].current_hp = 1
    engine.state.actors[F1].current_hp = 1
    events = _rider_use(engine, mid)
    saves = [e for e in events if e.event_type == "SAVE_ROLLED"]
    assert len(saves) == 3
    assert me.resources["resource:named.corruption"] == 1
    assert any(e.payload.get("mode") == "DISADVANTAGE" for e in saves)


def test_thousand_mouth_player_subset_spares_other_creatures_and_has_a_pb_bound():
    mid = "TAL_DAEMONIC_CULTIVATION_THOUSAND_MOUTH_DEVOURING_ART"
    engine = _rider_engine(mid, foes={F1: (5, 6), F2: (6, 6), F3: (7, 6), F4: (8, 6)})
    before = _hp(engine)
    seen = _answers(engine, {"rider_targets": [AN, F1]})
    _rider_use(engine, mid)
    assert engine.state.actors[AN].current_hp < before[AN]
    assert engine.state.actors[F1].current_hp < before[F1]
    assert all(engine.state.actors[who].current_hp == before[who] for who in (ME, F2, F3, F4))
    assert next(request["extension_choice"]["maximum_selections"] for request in seen
                if request["reaction_source_id"].endswith("rider_targets")) == PB


def test_hunger_breath_does_not_pay_a_defeat_reward_for_nonlethal_damage():
    mid = "TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH"
    engine = _rider_engine(mid, cl=1)
    me = engine.state.actors[ME]
    me.reaction_available = False
    # Devour Essence answers the failed save on its own (rider lane C13: combat/ext/devour_essence.py); this test is the talent's reward
    engine.typed_passive_rows[ME] = [row for row in engine.typed_passive_rows.get(ME, []) if row.get("block") != "devour_essence"]
    _rider_use(engine, mid, aim=engine.state.actors[AN].position)
    assert me.resources["resource:named.devoured_essence"] == 0


def test_demon_shadow_step_excludes_destinations_without_a_qualifying_adjacent_creature():
    mid = "TAL_DAEMONIC_CULTIVATION_DEMON_SHADOW_STEP"
    engine = _rider_engine(mid)
    action = _rider_action(engine, mid)
    assert not [c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id]
    engine.state.actors[AN].current_hp = 1
    candidates = [c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id]
    assert candidates
    assert all(engine.grid.distance_ft(c.destination, engine.state.actors[AN].position) <= 5 for c in candidates)


@pytest.mark.parametrize("seed", [False, True])
def test_heaven_spiting_recovery_requires_seed_and_stands_the_survivor(seed):
    mid = "TAL_DAEMONIC_CULTIVATION_HEAVEN_SPITING_RECOVERY"
    engine = _rider_engine(mid)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.current_hp = 2
    engine._apply_condition(me, "condition:typed.prone", "test", ME, expires_on="STAND_UP")
    if seed:
        engine._apply_condition(me, "condition:typed.stance.demon_seed", "test", ME, expires_on="UNTIL_REMOVED")
    from combat import typed_reactions
    pending = typed_reactions.on_damage(engine, me, 10, 0, source_actor_id=AN)
    engine._commit_damage(me, pending, "FORCE", "test:lethal", AN, None, reaction_depth=0)
    assert me.current_hp == (1 if seed else 0)
    if seed:
        assert not any(c.condition_id == "condition:typed.prone" for c in me.conditions.values())


CLAW = "TAL_DAEMONIC_CULTIVATION_BLACK_CLAW_MANIFESTATION"


def _claw_engine():
    engine = _rider_engine(CLAW)
    engine._apply_condition(engine.state.actors[ME], "condition:typed.stance.demon_seed", "test:seed", ME,
                            expires_on="UNTIL_REMOVED")
    return engine


@pytest.mark.parametrize("choice", ["temp_hp", "speed", "mark"])
def test_black_claw_activation_defers_the_selected_benefit_until_a_hit(choice):
    engine = _claw_engine()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    seen = _answers(engine, {"black_claw": [choice]})
    speed = engine._effective_speed(foe)
    _rider_use(engine, CLAW)
    assert me.temporary_hp == 0
    assert engine._effective_speed(foe) == speed
    assert not te.bears_mark(foe, ME, "Demon Mark")
    _rider_strike(engine, ME, AN)
    assert any(r["reaction_source_id"].endswith("black_claw") for r in seen)
    assert me.temporary_hp == (PB if choice == "temp_hp" else 0)
    assert engine._effective_speed(foe) == speed - (5 if choice == "speed" else 0)
    assert te.bears_mark(foe, ME, "Demon Mark") == (choice == "mark")
    if choice in {"speed", "mark"}:
        affected = list(foe.modifiers.values()) if choice == "speed" else list(foe.conditions.values())
        expiry = "START_OF_MARKER_NEXT_TURN" if choice == "mark" else "START_OF_SOURCE_NEXT_TURN"
        assert any(e.expires_on == expiry for e in affected)
        engine.state.current_actor_id = AN
        engine._system_start_turn()
        assert engine._effective_speed(foe) == speed - (5 if choice == "speed" else 0)
        assert te.bears_mark(foe, ME, "Demon Mark") == (choice == "mark")
        engine.state.current_actor_id = ME
        engine._system_start_turn()
        assert engine._effective_speed(foe) == speed
        assert not te.bears_mark(foe, ME, "Demon Mark")


def test_black_claw_requires_seed_and_paid_activation_then_ends_with_seed():
    from combat.ext.daemonic_riders import CLAW_STATE, SEED

    engine = _rider_engine(CLAW)
    me = engine.state.actors[ME]
    action = _rider_action(engine, CLAW)
    assert not [c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id]
    engine._apply_condition(me, SEED, "test:seed", ME, expires_on="UNTIL_REMOVED")
    _rider_strike(engine, ME, AN)
    assert me.temporary_hp == 0
    before = dict(me.resources)
    _rider_use(engine, CLAW)
    assert sum(before.get(k, 0) - v for k, v in me.resources.items()) == 1
    assert any(c.condition_id == CLAW_STATE for c in me.conditions.values())
    engine._remove_condition(me, SEED, "test:end")
    assert not any(c.condition_id == CLAW_STATE for c in me.conditions.values())
    _rider_strike(engine, ME, AN)
    assert me.temporary_hp == 0


def test_black_claw_hit_limit_is_shared_across_targets_and_natural_weapon_hits():
    engine = _claw_engine()
    _rider_use(engine, CLAW)
    seen = _answers(engine, {"black_claw": ["mark"]})
    _rider_strike(engine, ME, AN, kind="weapon")
    _rider_strike(engine, ME, AN, bonus=-100)
    assert not [r for r in seen if r["reaction_source_id"].endswith("black_claw")]
    # The executor classifies compiled natural-weapon actions as unarmed.
    from tests.test_reaction_effects_r6 import _typed_action, _use
    action = _typed_action(engine, ME, [{"type": "attack", "attack_kind": "melee", "on_hit": [
        {"type": "damage", "flat": 1, "damage_types": ["slashing"]}]}])
    action = action.model_copy(update={"source_definition_id": "action:test.natural.claw"})
    action.parameters["typed"]["numbers"]["attack_bonus"] = 100
    engine.action_catalog[action.source_definition_id] = action
    engine.state.actors[ME].action_ids += (action.source_definition_id,)
    engine.state.actors[ME].action_available = True
    _use(engine, ME, action, AN)
    assert te.bears_mark(engine.state.actors[AN], ME, "Demon Mark")
    _rider_strike(engine, ME, F1)
    assert not te.bears_mark(engine.state.actors[F1], ME, "Demon Mark")
    assert len([r for r in seen if r["reaction_source_id"].endswith("black_claw")]) == 1
    engine.state.current_slot_index += 1
    _rider_strike(engine, ME, F1)
    assert te.bears_mark(engine.state.actors[F1], ME, "Demon Mark")


def test_black_claw_step_moves_now_without_spending_ordinary_movement_or_exempting_other_enemies():
    from combat import ext
    engine = _claw_engine()
    _rider_use(engine, CLAW)
    me = engine.state.actors[ME]
    before, budget = me.position, me.movement_remaining_ft
    _answers(engine, {"black_claw": ["move"], "black_claw_step": ["cell:2,6"]})
    observed = []
    original = engine._resolve_leave_reach
    def leave(mover, start, destination, intent, **kwargs):
        observed.append((ext.run("opportunity_allowed", engine, engine.state.actors[AN], mover),
                         ext.run("opportunity_allowed", engine, engine.state.actors[F1], mover)))
        original(mover, start, destination, intent, **kwargs)
    engine._resolve_leave_reach = leave
    _rider_strike(engine, ME, AN)
    assert me.position != before
    assert me.movement_remaining_ft == budget
    assert observed and False in observed[0][0] and False not in observed[0][1]
    assert "black_claw_step_target" not in me.turn_flags


@pytest.mark.parametrize("damage_type", ["slashing", "piercing", "necrotic", "force"])
def test_black_claw_unarmed_damage_type_choice_preserves_the_attack_damage(damage_type):
    engine = _claw_engine()
    _rider_use(engine, CLAW)
    _answers(engine, {"black_claw_damage": [damage_type]})
    events = _rider_strike(engine, ME, AN)
    damage = next(e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.target_ids == (AN,))
    assert damage.payload["damage_type"].lower() == damage_type
    assert 2 <= damage.payload["rolled_or_pending_damage"] <= 5


def test_black_claw_hit_benefit_settles_after_defeating_the_last_enemy():
    engine = _claw_engine()
    _rider_use(engine, CLAW)
    assert engine.state.actors[ME].temporary_hp == 0
    for who, actor in engine.state.actors.items():
        if who not in (ME, AN):
            actor.current_hp = 0
            actor.active = actor.action_available = actor.bonus_action_available = actor.reaction_available = False
    engine.state.actors[AN].current_hp = 1
    _answers(engine, {"black_claw": ["temp_hp"]})
    _rider_strike(engine, ME, AN)
    assert engine.state.terminal_result is not None
    assert engine.state.actors[ME].temporary_hp == PB


def test_water_abyssal_seal_failure_prevents_healing_and_clear_speech_without_soaking():
    # Printed (A2R14): "On a failed save, ... it is Restrained; it cannot speak
    # clearly; it cannot regain Hit Points; ... On a successful save, it is Soaked
    # and cannot take Reactions." Soaked belongs to the SUCCESSFUL branch only.
    # _rider_engine's dc=50 makes this save fail, so Soaked must not appear here;
    # the row previously carried Soaked on the failed branch, which inverted the
    # printed rule (a creature that escaped the seal came out soaked).
    mid = "TAL_WATER_ABYSSAL_PRESSURE_SEAL"
    engine = _rider_engine(mid)
    _rider_use(engine, mid)
    foe = engine.state.actors[AN]
    assert any(c.condition_id == "condition:typed.silenced" for c in foe.conditions.values())
    assert not _bears(engine, AN, "Soaked")
    assert any(c.condition_id == "condition:typed.restrained" for c in foe.conditions.values())
    foe.current_hp = 10
    action = _rider_action(engine, mid)
    ctx = te.Context(engine, engine.state.actors[ME], action, None, {"numbers": {}}, [foe], foe, {})
    te.run_effects(ctx, [{"type": "healing", "applies_to": "target", "flat": 20}])
    assert foe.current_hp == 10


@pytest.mark.parametrize("mid", ["TAL_WATER_OCEAN_SOVEREIGN_INCARNATION", "TAL_WATER_COURT_OF_THE_ENDLESS_TIDE"])
def test_water_states_grant_one_shared_free_return_the_flow_each_turn(mid):
    engine = _rider_engine(mid)
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Return the Flow") and c.display_name.endswith("(free)")]
    _rider_use(engine, mid)
    free = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Return the Flow: Soak a Creature (free)")
    _rider_use_action(engine, free)
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Return the Flow") and c.display_name.endswith("(free)")]
    if "OCEAN" in mid:
        assert any(c.display_name == "Water Lash" and engine.action_catalog[c.source_definition_id].range_ft == 300
                   for c in engine.legal_candidates())


@pytest.mark.parametrize("soaked,picks", [(False, ["healing"]), (True, ["healing", "speech"])])
def test_crushing_current_resolves_the_full_pressure_menu_and_soaked_second_pick(soaked, picks):
    engine = _rider_engine("TAL_WATER_CRUSHING_CURRENT")
    if soaked:
        _mark(engine, AN, "Soaked")
    seen = _answers(engine, {"drowning_pressure": picks})
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Shape Current: Pressure Basin")
    _rider_use_action(engine, action, aim=engine.state.actors[AN].position)
    foe = engine.state.actors[AN]
    # Pressure Basin's save comes when the first hostile creature each round enters it or starts its turn there (printed),
    # not when it is placed (rider lane C13); Crushing Current rides that save.
    assert not seen and not any(m.target_field == "healing_reduction" for m in foe.modifiers.values())
    while engine.state.current_actor_id != AN:  # real End turn intents, as the table runs them
        end = next(c for c in engine.legal_candidates() if c.display_name == "End turn")
        engine.execute_intent(ActionIntent(intent_id=f"end-{engine.state.event_sequence}", decision_id=end.decision_id,
                                           candidate_id=end.candidate_id, state_version=end.state_version, actor_id=end.actor_id,
                                           target_ids=end.target_ids))
    assert seen and seen[0]["reactor_id"] == ME  # the Basin's owner chooses, on the foe's turn
    assert any(m.target_field == "healing_reduction" and m.value == "none" for m in foe.modifiers.values())
    assert any(c.condition_id == "condition:typed.silenced" for c in foe.conditions.values()) == soaked
    assert seen and seen[0]["extension_choice"]["maximum_selections"] == len(picks)


def test_flood_the_battlefield_saves_only_the_players_pb_bounded_subset():
    mid = "TAL_WATER_FLOOD_THE_BATTLEFIELD"
    engine = _rider_engine(mid, talents=["TAL_WATER_COURT_OF_THE_ENDLESS_TIDE"],
                           foes={F1: (5, 6), F2: (6, 6), F3: (7, 6), F4: (8, 6)})
    _rider_use(engine, "TAL_WATER_COURT_OF_THE_ENDLESS_TIDE")
    engine.state.actors[ME].action_available = True
    _answers(engine, {"rider_targets": [AN, F1]})
    events = _rider_use(engine, mid)
    assert len([e for e in events if e.event_type == "SAVE_ROLLED"]) == 2
    assert not any(c.condition_id == "condition:typed.prone" for c in engine.state.actors[F2].conditions.values())


def _rider_strike(engine, attacker, target, *, kind="unarmed", friendly=False, bonus=100):
    """A controlled engine attack checkpoint, after compiling the real rider owner."""
    from tests.test_reaction_effects_r6 import _typed_action, _use
    action = _typed_action(engine, attacker, [{"type": "attack", "attack_kind": kind, "on_hit": [
        {"type": "damage", "applies_to": "target", "flat": 1, "damage_types": ["bludgeoning"]}]}])
    action.parameters["typed"]["numbers"]["attack_bonus"] = bonus
    if friendly:
        action = action.model_copy(update={"target_kind": "ALLY_OR_SELF"})
        engine.action_catalog[action.source_definition_id] = action
    engine.state.actors[attacker].action_available = True
    before = len(engine.events)
    _use(engine, attacker, action, target)
    return engine.events[before:]


@pytest.mark.parametrize("cl,count", [(10, 2), (11, 3), (17, 4)])
def test_magma_armor_adds_scaled_damage_to_unarmed_hits_once_per_creature_per_turn(cl, count):
    mid = "TAL_MAGMA_MAGMA_ARMOR"
    engine = _rider_engine(mid, cl=cl)
    _rider_use(engine, mid)
    events = _rider_strike(engine, ME, AN)
    assert any(e.event_type == "DAMAGE_ROLLED" and e.payload.get("expression") == f"{count}d6+0" for e in events)
    events = _rider_strike(engine, ME, AN)
    assert not any(e.event_type == "DAMAGE_ROLLED" and e.payload.get("expression") == f"{count}d6+0" for e in events)


@pytest.mark.parametrize("mid", ["TAL_MAGMA_MAGMA_ARMOR", "TAL_MAGMA_OBSIDIAN_SKIN"])
def test_magma_damage_states_hurt_a_grappler_only_at_its_turn_start(mid):
    from combat import ext
    engine = _rider_engine(mid)
    _rider_use(engine, mid)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    hp = foe.current_hp
    engine._apply_condition(me, "condition:typed.grappled", "test:grip", AN, expires_on="UNTIL_REMOVED")
    assert foe.current_hp == hp
    ext.run("turn_start", engine, foe)
    assert foe.current_hp == hp
    assert any(e.event_type == "GM_RIDER" and AN in e.target_ids and "nested-event" in e.payload.get("rider", "")
               for e in engine.events)
    hp = foe.current_hp
    ext.run("turn_start", engine, foe)
    assert foe.current_hp == hp


def test_obsidian_skin_retaliates_on_a_melee_hit_once_per_attacker_per_turn():
    engine = _rider_engine("TAL_MAGMA_OBSIDIAN_SKIN")
    _rider_use(engine, "TAL_MAGMA_OBSIDIAN_SKIN")
    hp = engine.state.actors[AN].current_hp
    _rider_strike(engine, AN, ME)
    assert engine.state.actors[AN].current_hp == hp - PB
    _rider_strike(engine, AN, ME)
    assert engine.state.actors[AN].current_hp == hp - PB


def test_furnace_mantle_affects_only_first_nearby_hostile_turn_start_each_round():
    from combat import ext
    engine = _rider_engine("TAL_MAGMA_FURNACE_MANTLE", foes={F1: (3, 7), F2: (8, 7)})
    before = _hp(engine)
    _rider_use(engine, "TAL_MAGMA_FURNACE_MANTLE")
    assert _hp(engine) == before
    ext.run("turn_start", engine, engine.state.actors[AN])
    assert engine.state.actors[AN].current_hp == before[AN]
    assert len([e for e in engine.events if e.event_type == "GM_RIDER" and "nested-event" in e.payload.get("rider", "")]) == 1
    ext.run("turn_start", engine, engine.state.actors[F1])
    assert engine.state.actors[F1].current_hp == before[F1]
    engine.state.round_number += 1
    ext.run("turn_start", engine, engine.state.actors[F1])
    assert engine.state.actors[F1].current_hp == before[F1]
    assert len([e for e in engine.events if e.event_type == "GM_RIDER" and "nested-event" in e.payload.get("rider", "")]) == 2


def test_cinderglass_shards_leaves_the_printed_minute_obsidian_terrain():
    mid = "TAL_MAGMA_CINDERGLASS_SHARDS"
    engine = _rider_engine(mid)
    _rider_use(engine, mid, aim=engine.state.actors[AN].position)
    assert any(zone.active and zone.duration_rounds == 10 and "obsidian terrain" in (zone.trigger_profile.get("terrain") or [])
               for zone in engine.state.zones.values())


def test_furnace_pressure_replaces_the_casters_previous_choice_and_expires_on_targets_next_turn():
    from combat.ext import effect_durations, rider_damage_states
    engine = _rider_engine("TAL_MAGMA_FURNACE_MANTLE")
    _rider_use(engine, "TAL_MAGMA_FURNACE_MANTLE")
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    state = next(c for c in me.conditions.values() if c.condition_id.startswith(rider_damage_states.PREFIX))
    rows = state.data["spec"]["near_hostile_turn_start"]["effects"]
    rider_damage_states._fire(engine, me, foe, state, rows)
    ledger = next(c for c in foe.conditions.values() if c.data.get("label") == "Heat Pressure")
    old_modifiers = set(ledger.data["modifiers"])
    assert old_modifiers
    assert effect_durations.parse(ledger.expires_on) == ("start", AN, foe.turns_started + 1)
    _answers(engine, {"heat_pressure": ["reactions"]})
    engine.state.round_number += 1
    rider_damage_states._fire(engine, me, foe, state, rows)
    assert not old_modifiers.intersection(foe.modifiers)
    denied = next(c for c in foe.conditions.values() if c.condition_id == te.CONDITION_PREFIX + "reaction_denied")
    assert effect_durations.parse(denied.expires_on) == ("start", AN, foe.turns_started + 1)
    foe.turns_started += 1
    effect_durations.sweep(engine, foe, "START_OF_TURN")
    assert not any(c.condition_id == te.CONDITION_PREFIX + "reaction_denied" or c.data.get("label") == "Heat Pressure"
                   for c in foe.conditions.values())

# ------------------------------------------------------------------------------------------------------- harness


@pytest.mark.parametrize("mid,field", [
    ("tianxia.talent.source.root_cutting_pulse", "healing"),
    ("tianxia.talent.source.source_seal_pulse", "teleport"),
])
def test_source_pulse_failed_save_riders_execute_and_last_until_sources_next_turn(mid, field):
    engine = _rider_engine(mid, talents=("SOURCE_BASE_SOURCE_PULSE",))
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME
                  and (a.parameters.get("typed", {}).get("modifier") or {}).get("id") == mid)
    _rider_use_action(engine, action)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    # The new line is reached by a real compiled Source Pulse modifier. Probe
    # its consumer independently of the opponent's available abilities.
    ctx = te.Context(engine, foe, action, None, {"numbers": {"cl": 17, "pb": PB}}, [foe], foe, {})
    if field == "healing":
        hp = foe.current_hp
        te.run_effects(ctx, [{"type": "healing", "applies_to": "self", "flat": 5}])
        assert foe.current_hp == hp
        affected = [m for m in foe.modifiers.values() if m.target_field == "healing_reduction"]
    else:
        position = foe.position
        ctx.destination = position.model_copy(update={"x": position.x + 1})
        te.run_effects(ctx, [{"type": "movement", "mode": "teleport", "applies_to": "self", "distance_ft": 5}])
        assert foe.position == position
        affected = [c for c in foe.conditions.values() if c.condition_id == te.CONDITION_PREFIX + "cannot_teleport"]
    assert affected and all(row.expires_on == "START_OF_SOURCE_NEXT_TURN" for row in affected)


def test_blazing_armor_retaliates_on_every_hostile_melee_hit_and_not_an_allied_hit():
    engine = _rider_engine("tianxia.talent.fire.blazing_armor")
    _rider_use(engine, "tianxia.talent.fire.blazing_armor")
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.saving_throws["CON"] = 100  # keep the buff active across the repeated-hit control
    hp = foe.current_hp
    events = _rider_strike(engine, AN, ME)
    assert foe.current_hp < hp
    assert any(e.event_type == "DAMAGE_ROLLED" and e.actor_id == ME and e.payload["expression"].startswith("1d8") for e in events)
    hp = foe.current_hp
    _rider_strike(engine, AN, ME)
    assert foe.current_hp < hp  # no once-turn restriction is printed
    foe.team_id = me.team_id
    hp = foe.current_hp
    _rider_strike(engine, AN, ME, friendly=True)
    assert foe.current_hp == hp


def test_blazing_armor_still_retaliates_on_the_hit_that_ends_its_concentration():
    engine = _rider_engine("tianxia.talent.fire.blazing_armor")
    _rider_use(engine, "tianxia.talent.fire.blazing_armor")
    engine.state.actors[ME].saving_throws["CON"] = -100
    hp = engine.state.actors[AN].current_hp
    _rider_strike(engine, AN, ME)
    assert engine.state.actors[AN].current_hp < hp
    assert engine.state.actors[ME].concentration is None


def test_heaven_piercing_flame_lance_applies_all_three_followups_to_one_chosen_failed_target():
    mid = "tianxia.talent.fire.heaven_piercing_flame_lance"
    engine = _rider_engine(mid, foes={F1: (5, 6), F2: (3, 9)})
    for actor in engine.state.actors.values():
        actor.maximum_hp = 500
        actor.current_hp = 500
    _answers(engine, {"rider_failed_save": [F1]})
    _rider_use(engine, mid, aim=engine.state.actors[F1].position)
    for who in (AN, F1):
        actor = engine.state.actors[who]
        selected = who == F1
        assert any(c.condition_id == te.CONDITION_PREFIX + "reaction_denied" for c in actor.conditions.values()) == selected
        assert any(m.target_field == "resistance_suppressed" and m.value == "FIRE" for m in actor.modifiers.values()) == selected
        assert any(m.target_field == "healing_reduction" and m.value == "none" for m in actor.modifiers.values()) == selected


def test_crown_of_inferno_selects_one_burning_creature_in_its_placed_zone_at_owners_turn_start():
    from combat import ext
    mid = "FIRE_TAL_CROWN_OF_INFERNO"
    engine = _rider_engine(mid, foes={F1: (5, 6), F2: (10, 10)})
    _rider_use(engine, mid, aim=engine.state.actors[AN].position)
    for who in (AN, F1, F2):
        engine._apply_condition(engine.state.actors[who], te.CONDITION_PREFIX + "burning", "test:burn", ME,
                                expires_on="UNTIL_REMOVED")
    _answers(engine, {"rider_targets": [F1]})
    ext.run("turn_start", engine, engine.state.actors[ME])
    assert any(m.target_field == "healing_reduction" for m in engine.state.actors[F1].modifiers.values())
    assert not any(m.target_field == "healing_reduction" for m in engine.state.actors[AN].modifiers.values())
    assert not any(m.target_field == "healing_reduction" for m in engine.state.actors[F2].modifiers.values())


@pytest.mark.parametrize("pick", ["speed", "dash"])
def test_soft_body_hard_floor_runs_its_chosen_effect_only_after_a_response_talent_save_fails(pick):
    from combat.ext import flowing_river, effect_durations
    mid = "TAL_FLOWING_RIVER_SOFT_BODY_HARD_FLOOR"
    engine = _rider_engine(mid, talents=(flowing_river.RESPONSE, "TAL_FLOWING_RIVER_TURN_THE_FOOT"))
    _answers(engine, {"soft_floor": [pick]})
    engine._active_intent = ActionIntent(intent_id="response-trigger", decision_id="test", candidate_id="test",
                                         state_version=engine.state.state_version, actor_id=AN, target_ids=(ME,))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    flowing_river._succeed(engine, me, foe)
    if pick == "speed":
        assert engine._effective_speed(foe) == 0
        affected = [m for m in foe.modifiers.values() if m.target_field == "speed_ft" and m.value <= -30]
    else:
        affected = [c for c in foe.conditions.values() if c.condition_id == te.CONDITION_PREFIX + "no_dash"]
        ctx = te.Context(engine, foe, next(iter(engine.action_catalog.values())),
                         None, {"numbers": {}}, [], None, {})
        before = foe.movement_remaining_ft
        te.run_effects(ctx, [{"type": "movement", "applies_to": "self", "distance_ft": "speed"}])
        assert foe.movement_remaining_ft == before
    assert affected and all(effect_durations.parse(row.expires_on) == ("start", AN, foe.turns_started + 1) for row in affected)


@pytest.mark.parametrize("dc,far", [(-40, False), (50, True)])
def test_soft_floor_does_not_trigger_on_a_successful_save_or_outside_reach(dc, far):
    from combat.ext import flowing_river
    engine = _rider_engine("TAL_FLOWING_RIVER_SOFT_BODY_HARD_FLOOR", dc=dc,
                           talents=(flowing_river.RESPONSE, "TAL_FLOWING_RIVER_TURN_THE_FOOT"))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    if far:
        foe.position = foe.position.model_copy(update={"x": 7})
    flowing_river._succeed(engine, me, foe)
    assert engine._effective_speed(foe) != 0
    assert not any(c.condition_id == te.CONDITION_PREFIX + "no_dash" for c in foe.conditions.values())


def test_turning_guard_names_one_creature_at_dodge_and_responds_to_each_of_its_melee_misses():
    engine = _rider_engine("TAL_FLOWING_RIVER_TURNING_GUARD", foes={F1: (3, 7)})
    me = engine.state.actors[ME]
    seen = _answers(engine, {"turning_guard": [F1]})
    dodge = next(a for a in engine.action_catalog.values() if a.owner_id in (ME, "*") and a.resolution_kind == "DODGE")
    _rider_use_action(engine, dodge)
    assert any(q["reaction_source_id"].endswith("turning_guard") for q in seen)
    before = me.position
    _rider_strike(engine, AN, ME, bonus=-100)
    assert me.position == before
    _rider_strike(engine, F1, ME, bonus=-100)
    assert me.position != before
    before = me.position
    engine.state.actors[F1].position = before.model_copy(update={"x": before.x + 1})
    _rider_strike(engine, F1, ME, bonus=-100)
    assert me.position != before  # no extra once-turn limit appears in the owner text


@pytest.mark.parametrize("mid,ability", [("ASH_TAL_ASHEN_BURIAL", "STR"), ("ASH_TAL_CREMATION_PRISON", "CON")])
def test_ash_repeat_save_prisons_damage_at_target_turn_start_and_release_the_complete_effect(mid, ability):
    engine = _rider_engine(mid)
    foe = engine.state.actors[AN]
    foe.maximum_hp = 500
    foe.current_hp = 500
    engine._apply_condition(foe, te.CONDITION_PREFIX + "marked", "test:other", F1, expires_on="UNTIL_REMOVED")
    _rider_use(engine, mid)
    assert foe.current_hp == 500  # these damage rows say start of each turn, not activation
    assert any(c.condition_id == te.CONDITION_PREFIX + "restrained" for c in foe.conditions.values())
    engine.state.current_actor_id = AN
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    engine._system_start_turn()
    # AUTO75 2026-10-05: the printed "At the start of each of its turns, take 2d8 ... damage" is now real damage
    # (combat/ext/ash_talents.py periodic_damage_state) instead of a GM reminder about a suppressed nested event.
    assert 480 <= foe.current_hp <= 498, foe.current_hp
    assert [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]
    assert not [e for e in engine.events if e.event_type == "GM_RIDER" and "nested-event" in e.payload.get("rider", "")]
    foe.saving_throws[ability] = 100
    engine.end_turn()
    source = _rider_action(engine, mid).source_definition_id
    assert not any(c.source_definition_id == source for c in foe.conditions.values())
    assert not any(m.source_definition_id == source for m in foe.modifiers.values())
    assert engine.state.actors[ME].concentration is None
    assert any(c.source_definition_id == "test:other" for c in foe.conditions.values())


@pytest.mark.parametrize("pick", ["healing", "temporary_hp"])
def test_deep_cinder_brand_chooses_one_printed_pressure_instead_of_applying_every_existing_option(pick):
    mid = "ASH_TAL_DEEP_CINDER_BRAND"
    engine = _rider_engine(mid, talents=("ASH_BASE_CINDER_BRAND",))
    _answers(engine, {"deep_cinder_pressure": [pick]})
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME
                  and (a.parameters.get("typed", {}).get("modifier") or {}).get("id") == mid
                  and "Move Remnant" in a.display_name)
    _rider_use_action(engine, action)
    foe = engine.state.actors[AN]
    assert any(m.target_field == "healing_reduction" and m.value == "minus:4" for m in foe.modifiers.values()) == (pick == "healing")
    # Every Cinder Brand now applies Ashen Brand, whose own "cannot gain Temporary HP" rides the brand (rider lane C13,
    # combat/ext/ash_core.py: data "ashen_brand"); Deep Cinder Brand's pressure is the other no-Temporary-HP condition.
    assert any(c.condition_id == te.CONDITION_PREFIX + "no_temp_hp" and not (c.data or {}).get("ashen_brand")
               for c in foe.conditions.values()) == (pick == "temporary_hp")
    assert not any(c.condition_id == te.CONDITION_PREFIX + "concentration_mode" for c in foe.conditions.values())


def test_repeating_ash_prison_ends_only_its_own_held_concentration_copy():
    from combat import concentration
    mid = "ASH_TAL_ASHEN_BURIAL"
    engine = _rider_engine(mid)
    me, foe, other = engine.state.actors[ME], engine.state.actors[AN], engine.state.actors[F1]
    for actor in (foe, other):
        actor.maximum_hp = 500
        actor.current_hp = 500
    _rider_use(engine, mid)
    me.action_available = True
    _use_on(engine, _rider_action(engine, mid).display_name, F1)
    current = me.concentration.started_sequence
    assert concentration.held(me)
    engine.state.current_actor_id = AN
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    engine._system_start_turn()
    foe.saving_throws["STR"] = 100
    engine.end_turn()
    assert not concentration.held(me)
    assert me.concentration and me.concentration.started_sequence == current
    assert any(c.condition_id == te.CONDITION_PREFIX + "restrained" for c in other.conditions.values())


@pytest.mark.parametrize("incapacitating", ["incapacitated", "stunned"])
def test_beastmastery_court_ends_all_its_benefits_when_owner_is_incapacitated(incapacitating):
    mid = "TAL_BEASTMASTERY_COURT_OF_FANG_AND_REIN"
    engine = _rider_engine(mid)
    me = engine.state.actors[ME]
    mount = next(a for a in engine.state.actors.values() if (a.summon or {}).get("owner") == ME)
    _rider_use(engine, mid)
    source = _rider_action(engine, mid).source_definition_id
    for holder in (me, mount):
        assert any(m.source_definition_id == source and m.target_field == "speed_ft" and m.value == 10
                   for m in holder.modifiers.values())
    # A different effect on the same mount must survive Court's early ending.
    other = next(a for a in engine.action_catalog.values() if a.source_definition_id != source)
    te.run_effects(te.Context(engine, me, other, None, {"numbers": {}}, [mount], mount, {}),
                   [{"type": "speed", "applies_to": "target", "flat": 5, "duration": "one_minute"}])
    engine._apply_condition(me, te.CONDITION_PREFIX + "prone", "test:prone", AN, expires_on="UNTIL_REMOVED")
    assert any(m.source_definition_id == source for m in mount.modifiers.values())
    engine._apply_condition(me, te.CONDITION_PREFIX + incapacitating, "test:incapacitation", AN,
                            expires_on="UNTIL_REMOVED")
    assert not any(c.source_definition_id == source for holder in (me, mount) for c in holder.conditions.values())
    assert not any(m.source_definition_id == source for holder in (me, mount) for m in holder.modifiers.values())
    assert any(m.source_definition_id == other.source_definition_id and m.target_field == "speed_ft" and m.value == 5
               for m in mount.modifiers.values())


@pytest.mark.parametrize("attacker", ["caster", "ally"])
@pytest.mark.parametrize("temporary_hp", [0, 100])
def test_beast_tamer_ends_on_caster_or_ally_damage_including_temporary_hp(attacker, temporary_hp):
    mid = "TAL_BEASTMASTERY_BEAST_TAMER"
    engine = _rider_engine(mid)
    foe = engine.state.actors[AN]
    _rider_use(engine, mid)
    source = _rider_action(engine, mid).source_definition_id
    assert any(c.source_definition_id == source and c.condition_id == te.CONDITION_PREFIX + "charmed"
               for c in foe.conditions.values())
    engine._apply_condition(foe, te.CONDITION_PREFIX + "poisoned", "test:unrelated", F1,
                            expires_on="UNTIL_REMOVED")
    foe.temporary_hp = temporary_hp
    hp = foe.current_hp
    ally = next(a.entity_id for a in engine.state.actors.values()
                if (a.summon or {}).get("owner") == ME and a.summon.get("source") == "tamer")
    # Move the existing ally into legal melee reach, then run an ordinary typed hit.
    engine.state.actors[ally].position = foe.position.model_copy(update={"x": 5})
    _rider_strike(engine, ME if attacker == "caster" else ally, AN)
    assert not any(c.source_definition_id == source for c in foe.conditions.values())
    assert any(c.source_definition_id == "test:unrelated" for c in foe.conditions.values())
    if temporary_hp:
        assert foe.current_hp == hp and foe.temporary_hp < temporary_hp
    else:
        assert foe.current_hp < hp


def test_beast_tamer_ignores_damage_by_an_enemy_and_creates_no_ending_ledger_on_a_successful_save():
    mid = "TAL_BEASTMASTERY_BEAST_TAMER"
    engine = _rider_engine(mid)
    _rider_use(engine, mid)
    engine.state.actors[F1].position = engine.state.actors[AN].position.model_copy(update={"x": 5})
    _rider_strike(engine, F1, AN, friendly=True)
    assert any(c.condition_id == te.CONDITION_PREFIX + "charmed" for c in engine.state.actors[AN].conditions.values())
    engine = _rider_engine(mid, dc=-40)
    _rider_use(engine, mid)
    assert not any(c.condition_id.startswith("condition:typed.rider_break_on_allied_damage.")
                   for c in engine.state.actors[AN].conditions.values())


BOW_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1}]}}


def _sheet(talents, *, cl=10, dc=16, kit=None):
    sheet = L._sheet(LASH, cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(talents)
    if kit:
        sheet["equipment"] = [kit]
    return sheet


def _bundle(*talents, cl=10, dc=16, kit=None):
    return compile_character(_sheet(talents, cl=cl, dc=dc, kit=kit), actor_id=ME)


def _dummy(actor_id):
    sheet = L._sheet(GATHER)
    sheet.pop("spheres_and_talents")
    return compile_character(sheet, actor_id=actor_id)


def _engine(bundle, foes=None):
    """ME at (3,6) and the stock foe AN at (4,6); ``foes`` maps extra hostile actors to squares (5 feet each)."""
    foes = foes or {}
    positions = {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}, **{who: {"x": x, "y": y} for who, (x, y) in foes.items()}}
    engine = Gate4ControllerEngine(
        ROOT, match_seed="RIDERS1", typed_bundles=(bundle, *(_dummy(who) for who in foes)),
        roster_setup={"primary_actor_ids": [ME, *foes, AN], "team_by_actor": {ME: "team:a", AN: "team:b", **{who: "team:b" for who in foes}},
                      "starting_positions": positions})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for who in (AN, *foes):
        engine.state.actors[who].armor_class = -50
    roller = engine.roller
    original = roller._die

    def _die(sides):  # a natural 1 always misses: keep the technique's attack out of the dice
        value, counter = original(sides)
        return (max(2, value) if sides == 20 else value), counter

    roller._die = _die
    L._ready(engine)
    return engine


def _hp(engine):
    return {who: actor.current_hp for who, actor in engine.state.actors.items()}


def _mark(engine, who, name):
    action = next(iter(engine.action_catalog.values()))
    me, target = engine.state.actors[ME], engine.state.actors[who]
    ctx = te.Context(engine, me, action, None, {"numbers": {"pb": PB}}, [target], target, {})
    te.run_effects(ctx, [{"type": "mark", "mark": name, "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}}])


def _bears(engine, who, name="Charged"):
    return te.bears_mark(engine.state.actors[who], ME, name)


def _use_on(engine, name, target):
    # Reviewed hands change c18f4990: a bow needs the sword hand free.
    from tests.equipment_readiness import ready_weapon
    ready_weapon(engine, name, ME)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name and tuple(c.target_ids or ()) == (target,))
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=(target,), destination=candidate.destination))
    return engine.events[before:]


def _use_on_self(engine, name):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=tuple(candidate.target_ids or ()),
                                       destination=candidate.destination))
    return engine.events[before:]


def _committed(events):
    """{creature: lightning damage committed to it} for the events of one action."""
    out = {}
    for event in events:
        if event.event_type == "DAMAGE_COMMITTED":
            for who in event.target_ids or ():
                out[who] = out.get(who, 0) + int((event.payload or {}).get("rolled_or_pending_damage") or 0)
    return out


# ------------------------------------------------------------------------------------------------ Lightning: Arcs


def test_lash_arc_hits_a_conductive_neighbour_for_pb_and_skips_the_rest():
    """"Arc: ... you may Arc to a Charged or Conductive creature within 5 feet of the target; it takes lightning damage equal to
    your Proficiency Bonus": the Lash Arc option printed it as a GM line and changed nothing."""
    engine = _engine(_bundle(LASH), {F1: (5, 6), F2: (4, 7)})  # F1 and F2 both 5 feet from AN
    _mark(engine, F1, "Conductive")
    before = _hp(engine)
    damage = _committed(_use_on(engine, "Lightning Lash: Arc", AN))
    assert damage[F1] == PB and before[F1] - engine.state.actors[F1].current_hp == PB
    assert F2 not in damage and engine.state.actors[F2].current_hp == before[F2]  # not Charged or Conductive


def test_lash_arc_needs_a_conductive_creature_and_stops_at_five_feet():
    engine = _engine(_bundle(LASH), {F1: (5, 6), F2: (6, 6)})  # F2 is 10 feet from AN
    _mark(engine, F2, "Charged")  # in reach of nothing
    before = _hp(engine)
    assert _committed(_use_on(engine, "Lightning Lash: Arc", AN)).keys() == {AN}
    assert engine.state.actors[F2].current_hp == before[F2]
    _mark(engine, F1, "Conductive")  # 5 feet
    engine.state.actors[ME].action_available = True
    assert set(_committed(_use_on(engine, "Lightning Lash: Arc", AN))) == {AN, F1}


def test_arc_primer_reaches_ten_feet_and_charges_a_conductive_arc_target():
    """Arc Primer: "the Arc range of Lightning Lash is 10 feet instead of 5", and "if the Arc target is Conductive, it also
    becomes Charged until the start of your next turn"."""
    engine = _engine(_bundle(LASH, "TAL_LIGHTNING_ARC_PRIMER"), {F2: (6, 6)})  # 10 feet from AN
    _mark(engine, F2, "Conductive")
    assert not _bears(engine, F2, "Charged")
    assert _committed(_use_on(engine, "Lightning Lash: Arc", AN))[F2] == PB
    assert _bears(engine, F2, "Charged")


def test_arc_primer_no_longer_widens_the_lash_attack_itself():
    """The old typing gave Arc Primer a modifier that lengthened every Lash attack's range; the rule is about the Arc only."""
    bundle = _bundle(LASH, "TAL_LIGHTNING_ARC_PRIMER")
    assert not bundle["modifiers"]
    engine = _engine(bundle, {F2: (6, 6)})
    _mark(engine, F2, "Conductive")
    assert _committed(_use_on(engine, "Lightning Lash: Charge", AN)).keys() == {AN}  # only the Arc option arcs


def test_chain_bolt_second_target_takes_half_on_a_failed_save_and_is_charged():
    """Chain Bolt: "The second target makes a Dexterity saving throw. Failed Save: ... damage equal to half the Lightning Lash
    damage and becomes Charged. Successful Save: ... damage equal to your Proficiency Bonus and is not Charged"."""
    engine = _engine(_bundle("TAL_LIGHTNING_CHAIN_BOLT", dc=50), {F1: (5, 6)})
    damage = _committed(_use_on(engine, "Chain Bolt", AN))
    assert damage[F1] == damage[AN] // 2 > 0
    assert _bears(engine, AN) and _bears(engine, F1)


def test_chain_bolt_second_target_takes_pb_and_stays_uncharged_on_a_saved_throw():
    engine = _engine(_bundle("TAL_LIGHTNING_CHAIN_BOLT", dc=-40), {F1: (5, 6)})
    damage = _committed(_use_on(engine, "Chain Bolt", AN))
    assert damage[F1] == PB
    assert _bears(engine, AN) and not _bears(engine, F1)


def test_chain_bolt_third_arc_needs_both_targets_conductive_and_never_repeats_a_creature():
    """"If both targets were Conductive before this technique resolved, you may Arc to a third target within 15 feet of the
    second target ... No creature can be damaged more than once"."""
    foes = {F1: (5, 6), F2: (6, 6)}
    plain = _engine(_bundle("TAL_LIGHTNING_CHAIN_BOLT", dc=-40), foes)
    damage = _committed(_use_on(plain, "Chain Bolt", AN))
    assert set(damage) == {AN, F1}  # neither was Conductive: no third arc
    engine = _engine(_bundle("TAL_LIGHTNING_CHAIN_BOLT", dc=-40), foes)
    _mark(engine, AN, "Conductive")
    _mark(engine, F1, "Conductive")
    events = _use_on(engine, "Chain Bolt", AN)
    damage = _committed(events)
    assert set(damage) == {AN, F1, F2} and damage[F2] == PB and damage[F1] == PB
    assert sum(1 for e in events if e.event_type == "DAMAGE_COMMITTED" and F1 in (e.target_ids or ())) == 1


def test_chain_bolt_third_arc_is_denied_when_only_the_first_target_was_conductive():
    engine = _engine(_bundle("TAL_LIGHTNING_CHAIN_BOLT", dc=-40), {F1: (5, 6), F2: (6, 6)})
    _mark(engine, AN, "Conductive")
    assert set(_committed(_use_on(engine, "Chain Bolt", AN))) == {AN, F1}


def test_crackling_arrow_arcs_to_one_creature_within_five_feet_of_a_charged_target():
    """Crackling Arrow: "choose one creature within 5 feet of the target. That creature takes lightning damage equal to your
    Proficiency Bonus."  The old typing damaged every creature in the area."""
    engine = _engine(_bundle("TAL_LIGHTNING_CRACKLING_ARROW", GATHER), {F1: (5, 6), F2: (4, 7), F3: (6, 6)})
    _mark(engine, AN, "Charged")
    damage = _committed(_use_on(engine, "Lightning Lash: Jolt", AN))
    assert sum(1 for who in (F1, F2, F3) if who in damage) == 1  # one creature, not the whole area
    assert F3 not in damage and (damage.get(F1) or damage.get(F2)) == PB
    assert not _bears(engine, AN)  # the Charge was consumed


def test_crackling_arrow_reaches_fifteen_feet_at_cl_11():
    foes = {F3: (7, 6)}  # 15 feet from AN
    low = _engine(_bundle("TAL_LIGHTNING_CRACKLING_ARROW", GATHER, cl=10), foes)
    _mark(low, AN, "Charged")
    assert F3 not in _committed(_use_on(low, "Lightning Lash: Jolt", AN))
    high = _engine(_bundle("TAL_LIGHTNING_CRACKLING_ARROW", GATHER, cl=11), foes)
    _mark(high, AN, "Charged")
    assert _committed(_use_on(high, "Lightning Lash: Jolt", AN))[F3] == PB


def test_current_beyond_the_skin_raises_the_charge_limit_by_one_and_lasts_to_end_of_next_turn():
    """"Your Charge limit increases by 1", "Your Arc range increases to 15 feet", and "A target you Charge remains Charged
    until the end of your next turn instead of the start of your next turn"."""
    foes = {F1: (5, 6), F2: (6, 6), F3: (7, 6), F4: (8, 6)}
    everyone = (AN, *foes)
    base = _engine(_bundle(LASH), foes)
    for who in everyone:
        _mark(base, who, "Charged")
    assert sum(_bears(base, who) for who in everyone) == PB  # First Circuit Method: as many Charges as Proficiency Bonus
    better = _engine(_bundle(LASH, "TAL_LIGHTNING_CURRENT_BEYOND_THE_SKIN"), foes)
    for who in everyone:
        _mark(better, who, "Charged")
    assert sum(_bears(better, who) for who in everyone) == PB + 1
    expiries = {c.expires_on for who in everyone for c in better.state.actors[who].conditions.values() if "charged" in c.condition_id.lower()}
    assert expiries == {"END_OF_MARKER_NEXT_TURN"}
    assert {c.expires_on for who in everyone for c in base.state.actors[who].conditions.values() if "charged" in c.condition_id.lower()} == {
        "START_OF_MARKER_NEXT_TURN"}


def test_current_beyond_the_skin_makes_the_lash_arc_reach_fifteen_feet():
    engine = _engine(_bundle(LASH, "TAL_LIGHTNING_CURRENT_BEYOND_THE_SKIN"), {F3: (7, 6)})  # 15 feet from AN
    _mark(engine, F3, "Conductive")
    assert _committed(_use_on(engine, "Lightning Lash: Arc", AN))[F3] == PB


# ------------------------------------------------------------------------------------- Lightning: Circuits (multi-target)

FIVEFOLD, ONE_CIRCUIT, THOUSAND = ("TAL_LIGHTNING_FIVEFOLD_THUNDER_CIRCUIT", "TAL_LIGHTNING_ONE_CIRCUIT_UNDER_HEAVEN",
                                    "TAL_LIGHTNING_THOUSAND_SPARK_VOLLEY")
CROWD = {F1: (5, 6), F2: (6, 6), F3: (7, 6), F4: (8, 6)}  # AN + four more in a line, 5 feet apart


def _denied(engine, who):
    return any(c.condition_id.endswith("reaction_denied") or "reaction" in c.condition_id.lower() for c in engine.state.actors[who].conditions.values())


def test_fivefold_thunder_circuit_needs_each_later_target_conductive_or_charged():
    """"Each later target must be within 20 feet of a previous target and must be Conductive, Charged ...": the old typing
    saved only the creature clicked on, and the rest of the printed chain went to the GM."""
    engine = _engine(_bundle(FIVEFOLD, cl=15, dc=50), CROWD)
    _mark(engine, F1, "Conductive")
    _mark(engine, F3, "Charged")  # 10 feet from F1
    damage = _committed(_use_on(engine, "Fivefold Thunder Circuit", AN))
    assert set(damage) == {AN, F1, F3}, damage  # F2 and F4 are neither Conductive nor Charged
    assert all(amount > 0 for amount in damage.values())
    assert _bears(engine, AN) and _bears(engine, F3) and _bears(engine, F1)  # a failed save leaves each Charged


def test_fivefold_thunder_circuit_successful_save_halves_and_does_not_charge():
    engine = _engine(_bundle(FIVEFOLD, cl=15, dc=-40), CROWD)
    _mark(engine, F1, "Conductive")
    events = _use_on(engine, "Fivefold Thunder Circuit", AN)
    assert set(_committed(events)) == {AN, F1}
    assert not _bears(engine, AN) and not _bears(engine, F1, "Charged")


def test_fivefold_thunder_circuit_reaches_only_twenty_feet_past_a_previous_target():
    engine = _engine(_bundle(FIVEFOLD, cl=15, dc=50), {F1: (5, 6), F4: (10, 6)})  # F4 is 30 feet from AN, 25 from F1
    for who in (F1, F4):
        _mark(engine, who, "Conductive")
    assert set(_committed(_use_on(engine, "Fivefold Thunder Circuit", AN))) == {AN, F1}


def test_fivefold_thunder_circuit_three_failures_deny_reactions_around_one_of_them():
    """"If at least three targets fail their saves, choose one target that failed ... creatures of your choice within 10 feet
    of it cannot take Reactions until the start of their next turn"."""
    foes = {F1: (5, 6), F2: (6, 6), F3: (7, 6)}
    engine = _engine(_bundle(FIVEFOLD, cl=15, dc=50), foes)
    _mark(engine, F1, "Conductive")
    _mark(engine, F2, "Conductive")
    _use_on(engine, "Fivefold Thunder Circuit", AN)  # AN, F1, F2 fail; F3 stands 10 feet from F1 and is not struck
    assert _denied(engine, F3), "a bystander within 10 feet of a failed target loses Reactions"


def test_fivefold_thunder_circuit_two_failures_do_not_crack_the_thunder():
    engine = _engine(_bundle(FIVEFOLD, cl=15, dc=50), {F1: (5, 6), F3: (7, 6)})
    _mark(engine, F1, "Conductive")
    _use_on(engine, "Fivefold Thunder Circuit", AN)  # only AN and F1 fail
    assert not _denied(engine, F3)


def test_one_circuit_under_heaven_strikes_every_charged_creature_in_300_feet_and_takes_one_charge_each():
    """"Choose any number of Charged creatures ... you can see within range, up to twice your Proficiency Bonus. Each hostile
    creature ... Dexterity saving throw.  Failed Save: 6d8 lightning damage, cannot take Reactions ..., loses one Charge."
    The old typing struck only the creature targeted."""
    engine = _engine(_bundle(ONE_CIRCUIT, cl=15, dc=50), {F1: (8, 6), F2: (10, 6), F3: (12, 6)})
    for who in (AN, F1, F2):
        _mark(engine, who, "Charged")
    damage = _committed(_use_on(engine, "One Circuit Under Heaven", AN))
    assert set(damage) == {AN, F1, F2} and F3 not in damage, damage
    assert not any(_bears(engine, who) for who in (AN, F1, F2))  # each lost its Charge
    assert all(_denied(engine, who) for who in (AN, F1, F2))


def test_one_circuit_under_heaven_successful_save_halves_and_still_costs_the_charge():
    engine = _engine(_bundle(ONE_CIRCUIT, cl=15, dc=-40), {F1: (10, 6)})
    for who in (AN, F1):
        _mark(engine, who, "Charged")
    events = _use_on(engine, "One Circuit Under Heaven", AN)
    assert set(_committed(events)) == {AN, F1}
    assert not _bears(engine, AN) and not _bears(engine, F1)
    assert not _denied(engine, F1)  # "can take Reactions normally"


def test_thousand_spark_volley_saves_pb_secondary_targets_within_20_feet_of_the_first():
    """"Then choose a number of secondary targets up to your Proficiency Bonus within 20 feet of the first target. Each secondary
    target makes a Dexterity saving throw. Failed Save: 2d8 lightning damage and cannot take Reactions..."."""
    foes = {F1: (5, 6), F2: (6, 6), F3: (7, 6), F4: (12, 6)}  # F4 is 40 feet from AN
    engine = _engine(_bundle(THOUSAND, cl=15, dc=50, kit=BOW_KIT), foes)
    damage = _committed(_use_on(engine, "Thousand-Spark Volley", AN))
    assert {AN, F1, F2, F3} <= set(damage) and F4 not in damage, damage
    assert all(_denied(engine, who) for who in (F1, F2, F3)) and _bears(engine, AN)


def test_thousand_spark_volley_secondary_success_takes_half_and_no_reaction_denial():
    engine = _engine(_bundle(THOUSAND, cl=15, dc=-40, kit=BOW_KIT), {F1: (5, 6)})
    damage = _committed(_use_on(engine, "Thousand-Spark Volley", AN))
    assert F1 in damage and not _denied(engine, F1)


def test_thousand_spark_volley_miss_damages_one_secondary_target_not_the_missed_one():
    """"Miss: Choose one secondary target within 20 feet of the original target. It takes lightning damage equal to your
    Proficiency Bonus."  The old typing damaged the target that was missed."""
    engine = _engine(_bundle(THOUSAND, cl=15, dc=50, kit=BOW_KIT), {F1: (5, 6), F2: (6, 6)})
    engine.state.actors[AN].armor_class = 500  # the volley misses
    before = _hp(engine)
    damage = _committed(_use_on(engine, "Thousand-Spark Volley", AN))
    assert AN not in damage and engine.state.actors[AN].current_hp == before[AN]
    assert len([who for who in damage if who in (F1, F2)]) == 1 and set(damage.values()) == {PB}


# ------------------------------------------------------------------------------------------ Lightning: Thunder Arrow


def test_thunder_arrow_report_reaches_creatures_within_10_feet_of_the_target():
    """"Creatures of your choice within 10 feet of the target make a Constitution saving throw. Failed Save: ... thunder damage
    equal to your Proficiency Bonus and cannot take Reactions": the old typing made the target itself save again."""
    engine = _engine(_bundle("TAL_LIGHTNING_THUNDER_ARROW", cl=10, dc=50, kit=BOW_KIT), {F1: (5, 6), F2: (6, 6), F3: (7, 6)})
    damage = _committed(_use_on(engine, "Gong Jian (Bow and Arrow) attack + Thunder Arrow", AN))
    assert damage[F1] == PB and damage[F2] == PB and F3 not in damage  # F3 is 15 feet from AN
    assert _denied(engine, F1) and _denied(engine, F2) and not _denied(engine, F3)


def test_thunder_arrow_report_widens_to_15_feet_around_a_charged_target():
    engine = _engine(_bundle("TAL_LIGHTNING_THUNDER_ARROW", cl=10, dc=50, kit=BOW_KIT), {F2: (6, 6), F3: (7, 6), F4: (8, 6)})
    _mark(engine, AN, "Charged")
    damage = _committed(_use_on(engine, "Gong Jian (Bow and Arrow) attack + Thunder Arrow", AN))
    assert damage[F2] == PB and damage[F3] == PB and F4 not in damage  # F3 is 15 feet, F4 20 feet from AN


def test_thunder_arrow_report_is_no_extra_damage_on_a_successful_save():
    engine = _engine(_bundle("TAL_LIGHTNING_THUNDER_ARROW", cl=10, dc=-40, kit=BOW_KIT), {F1: (5, 6)})
    events = _use_on(engine, "Gong Jian (Bow and Arrow) attack + Thunder Arrow", AN)
    assert F1 not in _committed(events) and not _denied(engine, F1)


def test_thunder_arrow_only_rides_ranged_weapons_and_spends_cp_after_a_hit():
    engine = _engine(_bundle("TAL_LIGHTNING_THUNDER_ARROW", kit=BOW_KIT), {F1: (5, 6)})
    assert not any("Lightning Lash" in name and "Thunder Arrow" in name for name in _names(engine))
    me = engine.state.actors[ME]
    pool = "resource:core.qi"
    before = me.resources[pool]
    engine.state.actors[AN].armor_class = 500
    _use_on(engine, "Gong Jian (Bow and Arrow) attack + Thunder Arrow", AN)
    assert me.resources[pool] == before
    L._ready(engine)
    engine.state.actors[AN].armor_class = -50
    _use_on(engine, "Gong Jian (Bow and Arrow) attack + Thunder Arrow", AN)
    assert me.resources[pool] == before - 1


def test_thunder_arrow_report_can_choose_a_subset_including_an_ally():
    engine = _engine(_bundle("TAL_LIGHTNING_THUNDER_ARROW", kit=BOW_KIT, dc=50), {F1: (5, 6), F2: (6, 6)})
    engine.state.actors[F1].team_id = "team:a"
    _answers(engine, {"arc_area": (F1,)})
    damage = _committed(_use_on(engine, "Gong Jian (Bow and Arrow) attack + Thunder Arrow", AN))
    assert damage[F1] == PB and F2 not in damage
    assert _denied(engine, F1) and not _denied(engine, F2)


# ------------------------------------------------------------------------------------------ Lightning: Chains, Flash Reveal


def _move(engine, who, destination):
    """The creature's own willing move (its turn, one of its own Move candidates)."""
    engine.state.current_actor_id = who
    actor = engine.state.actors[who]
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    actor.movement_remaining_ft = 30
    # One of its own Move candidates, as the docstring says (rider lane C13: a CELL-aimed ability -- Gather Charge's Charged space --
    # also has a candidate at that square).
    candidate = next(c for c in engine.legal_candidates() if c.destination and (c.destination.x, c.destination.y) == destination
                     and getattr(c.kind, "value", c.kind) == "MOVE")
    engine.execute_intent(ActionIntent(intent_id=f"move-{who}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=who, target_ids=(), destination=candidate.destination))


def _linked(engine, who):
    return any(c.condition_id == "condition:typed.link.lightning" for c in engine.state.actors[who].conditions.values())


def test_lightning_chains_links_the_hit_creature_to_a_second_one_that_fails_its_save():
    """"You may spend 1 CP to create a short-lived lightning link between it and one creature within 15 feet. ... Failed Save: It
    takes lightning damage ... and both targets are linked": the old typing carried the whole talent as a GM line."""
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_CHAINS", cl=10, dc=50), {F1: (5, 6)})
    _mark(engine, AN, "Charged")
    damage = _committed(_use_on(engine, "Lightning Lash: Jolt + Lightning Chains", AN))
    assert damage[F1] > 0 and _linked(engine, AN) and _linked(engine, F1)


def test_lightning_chains_needs_a_charged_target_and_a_failed_save_to_link():
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_CHAINS", cl=10, dc=50), {F1: (5, 6)})
    _use_on(engine, "Lightning Lash: Jolt + Lightning Chains", AN)  # AN is not Charged
    assert not _linked(engine, F1) and not _linked(engine, AN)
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_CHAINS", cl=10, dc=-40), {F1: (5, 6)})
    _mark(engine, AN, "Charged")
    damage = _committed(_use_on(engine, "Lightning Lash: Jolt + Lightning Chains", AN))
    assert damage[F1] > 0 and not _linked(engine, F1)  # "half damage and no link forms"


def test_lightning_chains_link_snaps_when_a_linked_creature_walks_more_than_10_feet_away():
    """"While linked, if either target willingly moves more than 10 feet away from the other, it takes lightning damage equal
    to your Proficiency Bonus and the link ends"""
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_CHAINS", cl=10, dc=50), {F1: (5, 6)})
    _mark(engine, AN, "Charged")
    _use_on(engine, "Lightning Lash: Jolt + Lightning Chains", AN)
    before = engine.state.actors[F1].current_hp
    link = next(c for c in engine.state.actors[F1].conditions.values() if c.data.get("with") == AN)
    amount = link.data["damage"]
    assert amount == 4
    start = len(engine.events)
    _move(engine, F1, (8, 6))  # 20 feet from AN
    # The reviewed chain-link implementation now applies the printed PB damage
    # automatically instead of leaving that consequence as a GM rider.
    assert before - engine.state.actors[F1].current_hp == amount
    damage = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED"
              and e.source_definition_id == link.source_definition_id]
    assert len(damage) == 1 and damage[0].target_ids == (F1,)
    assert damage[0].payload["reduced_to"] == amount
    assert damage[0].payload["damage_type"] == "LIGHTNING"
    assert not _linked(engine, F1) and not _linked(engine, AN)


def test_lightning_chains_link_holds_for_a_short_step():
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_CHAINS", cl=10, dc=50), {F1: (5, 6)})
    _mark(engine, AN, "Charged")
    _use_on(engine, "Lightning Lash: Jolt + Lightning Chains", AN)
    before = engine.state.actors[F1].current_hp
    _move(engine, F1, (6, 6))  # 10 feet from AN: not more than 10
    assert engine.state.actors[F1].current_hp == before and _linked(engine, F1)


def test_flash_reveal_at_foundation_also_reveals_another_charged_creature_within_10_feet():
    """"At Foundation Realm, if the target is within 10 feet of another Charged creature, you may reveal both creatures with
    the same effect": the second creature was a GM line."""
    def revealed(cl):
        engine = _engine(_bundle("TAL_LIGHTNING_FLASH_REVEAL", cl=cl, dc=50), {F1: (6, 6)})
        _mark(engine, F1, "Charged")
        events = _use_on(engine, "Lightning Lash: Jolt", AN)  # Flash Reveal is free: it rides every Lash
        return [e for e in events if e.event_type == "MODIFIER_APPLIED" and F1 in (e.target_ids or ())]

    assert revealed(5) and not revealed(4)


def test_lightning_god_body_charges_a_creature_that_misses_you_with_an_opportunity_attack():
    """"When a creature misses you with an Opportunity Attack, you may place a Charge on that creature": a GM line before."""
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_GOD_BODY", cl=10), {F1: (2, 6)})
    _use_on_self(engine, "Lightning-God Body")
    engine.state.actors[ME].armor_class = 500  # F1's opportunity attack misses
    _move(engine, ME, (3, 8))
    assert _bears(engine, F1)


def test_lightning_god_body_does_nothing_for_a_creature_when_the_body_is_off():
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_GOD_BODY", cl=10), {F1: (2, 6)})
    engine.state.actors[ME].armor_class = 500
    _move(engine, ME, (3, 8))
    assert not _bears(engine, F1)


# ------------------------------------------------------------------------ Lightning: Court and Sovereign Incarnation

COURT, SOVEREIGN = "TAL_LIGHTNING_COURT_OF_CHARGED_PATHS", "TAL_LIGHTNING_LIGHTNING_SOVEREIGN_INCARNATION"
FIVE = {F1: (5, 6), F2: (6, 6), F3: (7, 6), F4: (8, 6)}


def _charges(engine, who=None):
    return [w for w in ((AN, F1, F2, F3, F4) if who is None else who) if w in engine.state.actors and _bears(engine, w)]


def _charge_everyone(engine):
    for who in (AN, F1, F2, F3, F4):
        _mark(engine, who, "Charged")


def test_court_of_charged_paths_raises_the_charge_limit_by_the_proficiency_bonus():
    """"Your Charge limit increases by your Proficiency Bonus": the limit stayed at PB (4) for the whole court."""
    plain = _engine(_bundle(COURT, cl=10), FIVE)
    _charge_everyone(plain)
    assert len(_charges(plain)) == PB
    court = _engine(_bundle(COURT, cl=10), FIVE)
    _use_on_self(court, "Court of Charged Paths")
    _charge_everyone(court)
    assert len(_charges(court)) == 5  # the court lifts it to PB + PB = 8; only five foes are here


def test_sovereign_incarnation_doubles_the_charge_limit():
    engine = _engine(_bundle(SOVEREIGN, cl=15), {**FIVE, "actor:riders.f5": (9, 6), "actor:riders.f6": (10, 6), "actor:riders.f7": (11, 6),
                                                 "actor:riders.f8": (12, 6)})
    _use_on_self(engine, "Lightning Sovereign Incarnation")
    for who in (AN, F1, F2, F3, F4, "actor:riders.f5", "actor:riders.f6", "actor:riders.f7", "actor:riders.f8"):
        _mark(engine, who, "Charged")
    assert len(_charges(engine, (AN, F1, F2, F3, F4, "actor:riders.f5", "actor:riders.f6", "actor:riders.f7", "actor:riders.f8"))) == 2 * PB


def test_court_of_charged_paths_first_lightning_damage_each_round_denies_reactions():
    """"The first time each round a hostile creature inside the court takes lightning damage from one of your talents, it cannot
    take Reactions until the start of its next turn."""
    engine = _engine(_bundle(COURT, cl=10, dc=50), {})
    _use_on_self(engine, "Court of Charged Paths")
    _use_on(engine, "Lightning Lash: Charge", AN)
    assert _denied(engine, AN)
    plain = _engine(_bundle(COURT, cl=10, dc=50), {})
    _use_on(plain, "Lightning Lash: Charge", AN)
    assert not _denied(plain, AN)


def test_court_does_not_count_item_lightning_as_talent_damage_but_sovereign_does():
    court = _engine(_bundle(COURT, cl=10), {})
    _use_on_self(court, "Court of Charged Paths")
    court._commit_damage(court.state.actors[AN], 1, "LIGHTNING", "item:test_lightning", ME, None, reaction_depth=0)
    assert not _denied(court, AN)
    _use_on(court, "Lightning Lash: Charge", AN)
    assert _denied(court, AN)
    sovereign = _engine(_bundle(SOVEREIGN, cl=15), {})
    _use_on_self(sovereign, "Lightning Sovereign Incarnation")
    sovereign._commit_damage(sovereign.state.actors[AN], 1, "LIGHTNING", "item:test_lightning", ME, None, reaction_depth=0)
    assert _denied(sovereign, AN)


def test_sovereign_incarnation_first_lightning_damage_each_round_denies_reactions():
    engine = _engine(_bundle(SOVEREIGN, cl=15), {})
    _use_on_self(engine, "Lightning Sovereign Incarnation")
    _use_on(engine, "Lightning Lash: Charge", AN)
    assert _denied(engine, AN)


def test_court_of_charged_paths_moves_a_charge_from_a_hostile_starting_its_turn_charged():
    """"When a hostile creature starts its turn Charged inside the court, you may move the Charge to another visible creature within
    10 feet of it."""
    engine = _engine(_bundle(COURT, cl=10), {F1: (5, 6), F2: (6, 6)})
    _use_on_self(engine, "Court of Charged Paths")
    _mark(engine, F1, "Charged")
    engine.state.current_actor_id = F1
    engine._system_start_turn()
    assert not _bears(engine, F1) and _bears(engine, F2)  # AN and F2 are each 5 feet from F1; the nearest, by id, gets it


def test_court_transfers_the_charge_without_refreshing_it_or_triggering_storm_heart_consumption():
    engine = _engine(_bundle(COURT, "TAL_LIGHTNING_STORM_HEART_ENGINE", cl=10), {F1: (5, 6), F2: (6, 6)})
    _use_on_self(engine, "Court of Charged Paths")
    _mark(engine, F1, "Charged")
    original = next(c for c in engine.state.actors[F1].conditions.values() if c.condition_id == te.mark_condition_id("Charged", ME))
    engine.state.current_actor_id = F1
    engine._system_start_turn()
    moved = next(c for c in engine.state.actors[F2].conditions.values() if c.condition_id == te.mark_condition_id("Charged", ME))
    assert moved.expires_on == original.expires_on and moved.data == original.data
    assert engine.state.actors[ME].temporary_hp == 0


def test_gather_charge_reaches_60_feet_from_foundation_realm():
    """"At Foundation Realm, the range becomes 60 feet": the printed line was a GM rider and the range stayed 30 feet."""
    # Gather Charge's targets are you, a willing creature, your weapon or a square (rider lane C13: it was aimed at an enemy), so the
    # reach is read from its Charged-space option: a square 45 feet away.
    def targets(cl):
        engine = _engine(_bundle(GATHER, cl=cl), {F1: (12, 6)})  # (12, 6) is 45 feet from ME
        return {(c.destination.x, c.destination.y) for c in engine.legal_candidates()
                if c.display_name.startswith("Gather Charge: Charge a 5-foot Space") and c.destination is not None}

    assert (12, 7) in targets(5) and (12, 7) not in targets(4)


def _cast_at(engine, name, destination):
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith(name) and c.destination is not None
                     and (c.destination.x, c.destination.y) == destination)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=tuple(candidate.target_ids or ()),
                                       destination=candidate.destination))


def test_conductive_field_makes_the_creatures_inside_conductive_for_an_arc():
    """"The area is Conductive.": a Lightning Lash Arc reaches an unmarked creature standing in the field, not one outside it."""
    engine = _engine(_bundle("TAL_LIGHTNING_CONDUCTIVE_FIELD", cl=10, dc=-40), {F1: (5, 6), F2: (3, 5)})
    _cast_at(engine, "Conductive Field", (6, 6))  # 10-foot radius: F1 at (5,6) is inside, F2 at (3,5) is 15 feet out
    L._ready(engine)  # a second Action, as if on the next turn
    damage = _committed(_use_on(engine, "Lightning Lash: Arc", AN))
    assert damage[F1] == PB and F2 not in damage


# --------------------------------------------------------- Lightning: Wings, World-Nerve Judgment, Prison Bars, Potential

WINGS, WORLD_NERVE, BARS = ("TAL_LIGHTNING_LIGHTNING_WINGS_OF_THE_HEAVENLY_BODY", "TAL_LIGHTNING_WORLD_NERVE_JUDGMENT",
                            "TAL_LIGHTNING_LIGHTNING_PRISON_BARS")
GOD_BODY = "TAL_LIGHTNING_LIGHTNING_GOD_BODY"


def _hits_on(events, who):
    return [e for e in events if e.event_type == "DAMAGE_COMMITTED" and who in (e.target_ids or ())]


def test_wings_of_the_heavenly_body_adds_2d8_after_30_feet_of_movement_while_a_lightning_god_state_is_on():
    """"Once per turn when you move at least 30 feet before hitting a target with a Lightning attack ... add 2d8 lightning
    damage to the hit"; the typed modifier applied it to every hit, moved or not, a Body on or not."""
    def hit(*, state, move):
        engine = _engine(_bundle(WINGS, GOD_BODY, cl=15), {F1: (3, 13)})  # F1 is 35 feet south of ME
        if state:
            _use_on_self(engine, "Lightning-God Body")
        if move:
            _move(engine, ME, (3, 12))  # six squares, all toward F1
        L._ready(engine)
        return len(_hits_on(_use_on(engine, "Lightning Lash: Charge", F1), F1))

    # the Lash; God Body's own once-a-turn Proficiency Bonus; and Wings' 2d8 only when a state is on and the 30 feet were walked
    assert hit(state=False, move=True) == 1
    assert hit(state=True, move=False) == 2
    assert hit(state=True, move=True) == 3


def test_wings_counts_movement_in_any_direction_and_only_spends_its_limit_when_qualified():
    engine = _engine(_bundle(WINGS, GOD_BODY, cl=15), {})
    engine.state.actors[AN].maximum_hp = 2000
    engine.state.actors[AN].current_hp = 2000
    _use_on_self(engine, "Lightning-God Body")
    L._ready(engine)
    assert len(_hits_on(_use_on(engine, "Lightning Lash: Charge", AN), AN)) == 2
    _move(engine, ME, (3, 12))  # 30 feet away from the target: no printed approach requirement
    L._ready(engine)
    assert len(_hits_on(_use_on(engine, "Lightning Lash: Charge", AN), AN)) == 2  # Lash and Wings; Body already used
    L._ready(engine)
    assert len(_hits_on(_use_on(engine, "Lightning Lash: Charge", AN), AN)) == 1


@pytest.mark.parametrize("talent,name", [
    (GOD_BODY, "Lightning-God Body"), (SOVEREIGN, "Lightning Sovereign Incarnation"), (COURT, "Court of Charged Paths")])
def test_lightning_states_and_their_benefits_end_when_incapacitated(talent, name):
    from combat.ext import states

    engine = _engine(_bundle(talent, cl=15), {})
    _use_on_self(engine, name)
    assert any(c.condition_id.startswith(states.PREFIX) for c in engine.state.actors[ME].conditions.values())
    me = engine.state.actors[ME]
    source = next(c.source_definition_id for c in me.conditions.values() if c.condition_id.startswith(states.PREFIX))
    engine._apply_condition(me, "condition:typed.stunned", "test:stun", AN, expires_on="UNTIL_REMOVED")
    assert not any(c.source_definition_id == source for c in me.conditions.values())
    assert not any(m.source_definition_id == source for m in me.modifiers.values())


def test_world_nerve_judgment_forces_a_concentration_save_with_disadvantage_on_a_failed_save():
    """"Failed Save: ... immediately makes one Concentration save ... with Disadvantage": the Concentration save was a GM line."""
    engine = _engine(_bundle(WORLD_NERVE, cl=15, dc=50), {})
    target = engine.state.actors[AN]
    # the target holds a Concentration the technique can break
    target.concentration = ConcentrationState(source_definition_id="test:held", started_sequence=1)
    original = engine.roller._die
    engine.roller._die = lambda sides: (lambda row: (20 if sides == 20 else row[0], row[1]))(original(sides))  # every d20 is a 20: the
    # save against the damage itself is passed, so the forced one is the one that matters
    events = _use_on(engine, "World-Nerve Judgment", AN)
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and "CONCENTRATION" in str((e.payload or {}).get("reason", "")).upper()]
    assert [e.payload.get("mode") for e in saves][-1] == "DISADVANTAGE", [e.payload.get("mode") for e in saves]


def test_world_nerve_judgment_checks_each_held_concentration_on_a_failed_save():
    from combat import concentration

    engine = _engine(_bundle(WORLD_NERVE, cl=15, dc=50), {})
    target = engine.state.actors[AN]
    target.maximum_hp = 2000
    target.current_hp = 2000
    target.concentration = ConcentrationState(source_definition_id="test:older", started_sequence=1)
    concentration.hold_current(engine, target)
    target.concentration = ConcentrationState(source_definition_id="test:newer", started_sequence=2)
    original = engine.roller._die
    engine.roller._die = lambda sides: (lambda row: (20 if sides == 20 else row[0], row[1]))(original(sides))
    events = _use_on(engine, "World-Nerve Judgment", AN)
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and "CONCENTRATION" in str((e.payload or {}).get("reason", "")).upper()]
    assert [e.payload.get("mode") for e in saves][-2:] == ["DISADVANTAGE", "DISADVANTAGE"]
    assert not concentration.sources(target)


def test_lightning_prison_bars_needs_a_charged_target_or_one_in_a_conductive_field():
    """"Target: One Charged creature or one creature standing inside a Conductive Field": offered against no other creature."""
    engine = _engine(_bundle(BARS, cl=15, dc=50), {F1: (5, 6)})

    def offered():
        return {t for c in engine.legal_candidates() if c.display_name == "Lightning Prison Bars" for t in c.target_ids or ()}

    assert offered() == set()
    _mark(engine, F1, "Charged")
    assert offered() == {F1}


@pytest.mark.parametrize("benefit_before_repeat", [False, True])
def test_lightning_prison_thunder_only_disadvantages_the_next_repeat_save(benefit_before_repeat):
    engine = _engine(_bundle(BARS, cl=15, dc=50), {})
    _mark(engine, AN, "Charged")
    _use_on(engine, "Lightning Prison Bars", AN)
    target = engine.state.actors[AN]
    bars = next(c for c in target.conditions.values() if c.condition_id == "condition:typed.restrained")
    engine.state.current_actor_id = AN
    engine._system_start_turn()
    assert any(c.condition_id == "condition:typed.restrained" for c in target.conditions.values())
    def grant_benefit():
        engine._apply_condition(target, "condition:typed.test_dex_benefit", "test:benefit", AN, expires_on="UNTIL_REMOVED",
                                data={"rule": {"save_mode": {"DEX": "ADVANTAGE"}}})
    # Advantage and Disadvantage cancel, regardless of how many sources supply
    # either. The reviewed lock save path must not stack a second Disadvantage.
    if benefit_before_repeat:
        grant_benefit()
    engine._commit_damage(target, 0, "THUNDER", "test:absorbed", ME, None, reaction_depth=0)
    assert not any(c.condition_id.startswith("condition:typed.prison_thunder.") for c in target.conditions.values())
    engine._commit_damage(target, 1, "THUNDER", "test:thunder", ME, None, reaction_depth=0)
    start = len(engine.events)
    engine._expire_for_checkpoint("END_OF_TURN", AN)  # runs the engine's real repeat-save path
    saves = [e for e in engine.events[start:] if e.event_type == "SAVE_ROLLED" and e.source_definition_id == bars.source_definition_id]
    assert len(saves) == 1 and saves[0].payload["mode"] == ("NORMAL" if benefit_before_repeat else "DISADVANTAGE")
    assert not any(c.condition_id.startswith("condition:typed.prison_thunder.") for c in target.conditions.values())
    if not benefit_before_repeat:
        grant_benefit()
    engine._expire_for_checkpoint("END_OF_TURN", AN)
    saves = [e for e in engine.events[start:] if e.event_type == "SAVE_ROLLED" and e.source_definition_id == bars.source_definition_id]
    assert saves[-1].payload["mode"] == "NORMAL"


def test_body_becomes_thunder_adds_4d8_to_the_first_lightning_attack_each_turn():
    """"The first time each turn you hit with a Lightning attack, it deals additional lightning damage equal to 4d8": a GM line."""
    engine = _engine(_bundle("tianxia.talent.lightning.when_potential_becomes_judgment", cl=17), {})
    _use_on_self(engine, "When Potential Becomes Judgment: Body Becomes Thunder")
    L._ready(engine)
    assert len(_hits_on(_use_on(engine, "Lightning Lash: Charge", AN), AN)) == 2  # the Lash and the 4d8
    L._ready(engine)
    assert len(_hits_on(_use_on(engine, "Lightning Lash: Charge", AN), AN)) == 1  # once each turn


def test_body_becomes_thunder_does_not_add_to_fire_or_spend_the_lightning_limit_on_it():
    engine = _engine(_bundle("FIRE_BASE_IGNITE", "tianxia.talent.lightning.when_potential_becomes_judgment", cl=17), {})
    engine.state.actors[AN].maximum_hp = 2000
    engine.state.actors[AN].current_hp = 2000
    _use_on_self(engine, "When Potential Becomes Judgment: Body Becomes Thunder")
    L._ready(engine)
    assert len(_hits_on(_use_on(engine, "Ignite: Increase Burn Damage", AN), AN)) == 1
    L._ready(engine)
    assert len(_hits_on(_use_on(engine, "Lightning Lash: Charge", AN), AN)) == 2


def _names(engine):
    return {c.display_name for c in engine.legal_candidates()}


def test_court_of_charged_paths_gives_one_free_gather_charge_a_turn():
    """"Once on each of your turns, you may use Gather Charge without an action": a GM line before."""
    engine = _engine(_bundle(COURT, cl=10), {})
    # Gather Charge is now its printed options (rider lane C13): "Gather Charge: Charge Yourself (free)" and the rest.
    free = "Gather Charge: Charge Yourself (free)"
    assert free not in _names(engine)  # not while the court is down
    _use_on_self(engine, "Court of Charged Paths")  # a Bonus Action: the Bonus Action is spent
    assert "Gather Charge: Charge Yourself" not in _names(engine) and free in _names(engine)
    _use_on_self(engine, free)
    assert _bears(engine, ME)
    assert free not in _names(engine)  # once on each of your turns


def test_sovereign_incarnation_gives_one_free_lash_or_gather_charge_a_turn():
    engine = _engine(_bundle(SOVEREIGN, cl=15), {})
    _use_on_self(engine, "Lightning Sovereign Incarnation")
    engine.state.actors[ME].action_available = False  # even with the Action spent
    assert "Lightning Lash: Charge (free)" in _names(engine) and "Gather Charge: Charge Yourself (free)" in _names(engine)
    _use_on(engine, "Lightning Lash: Charge (free)", AN)
    assert not {n for n in _names(engine) if n.endswith("(free)")}  # one use for the pair


def test_sovereign_incarnation_reaches_with_lash_at_300_feet_including_the_free_copy():
    engine = _engine(_bundle(SOVEREIGN, cl=15), {F1: (19, 6)})  # 80 feet away on the stock map: outside ordinary Lash range

    def targets(name):
        return {t for c in engine.legal_candidates() if c.display_name == name for t in c.target_ids or ()}

    assert F1 not in targets("Lightning Lash: Charge")
    _use_on_self(engine, "Lightning Sovereign Incarnation")
    assert F1 in targets("Lightning Lash: Charge") and F1 in targets("Lightning Lash: Charge (free)")
    action = next(a for a in engine.action_catalog.values() if (a.parameters or {}).get("state_range_rule")
                  and a.display_name == "Lightning Lash: Charge")
    assert action.range_ft == action.parameters["typed"]["range_ft"] == 300
    assert _committed(_use_on(engine, "Lightning Lash: Charge (free)", F1))[F1] > 0


# ------------------------------------------------------------------------------------------------ Lightning: Storm-Heart Engine

STORM_HEART, ARROW = "TAL_LIGHTNING_STORM_HEART_ENGINE", "TAL_LIGHTNING_CRACKLING_ARROW"


def _answers(engine, table):
    """A player answering the choices: ``table`` maps the suffix after "choice:needle." to the option ids to pick."""
    from combat.gate2_runtime_models import ReactionDecision

    seen = []

    def provider(request):
        base = dict(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"])
        if "extension_choice" not in request:  # an ordinary reaction window: nobody reacts
            return ReactionDecision(**base, selection="DECLINE", option_ids=()), None
        seen.append(request)
        key = request["reaction_source_id"].split("choice:needle.")[-1]
        spec = request["extension_choice"]
        pick = table.get(key) or (spec.get("preferred_option_ids") or spec["option_ids"])[:spec["maximum_selections"]]
        return ReactionDecision(**base, selection="USE", option_ids=tuple(pick)), None

    engine.set_reaction_provider(provider)
    return seen


def _consume_a_charge(engine):
    _mark(engine, AN, "Charged")
    return _use_on(engine, "Lightning Lash: Jolt", AN)  # Crackling Arrow rides every Lash


def test_storm_heart_engine_offers_its_printed_benefits_and_pays_the_one_chosen():
    """"Once per turn when you consume a Charge ..., choose one: Temporary HP; move 5 feet without provoking; ... Disadvantage on the
    next Opportunity Attack against you": it always paid the Temporary HP."""
    engine = _engine(_bundle(STORM_HEART, ARROW, cl=10), {})
    seen = _answers(engine, {"storm_heart": ("move",)})
    me = engine.state.actors[ME]
    before, budget = me.position.model_copy(), me.movement_remaining_ft
    _consume_a_charge(engine)
    assert seen and set(seen[0]["legal_option_ids"]) == {"temp_hp", "move", "oa_disadvantage"}
    assert me.position != before and me.temporary_hp == 0
    assert me.movement_remaining_ft == budget and not me.turn_flags.get("oa_free_ft")

    engine = _engine(_bundle(STORM_HEART, ARROW, cl=10), {})
    _answers(engine, {"storm_heart": ("oa_disadvantage",)})
    _consume_a_charge(engine)
    assert any(c.condition_id == "condition:typed.storm_heart_oa_disadvantage" for c in engine.state.actors[ME].conditions.values())


def test_storm_heart_engine_unanswered_takes_the_temporary_hp():
    engine = _engine(_bundle(STORM_HEART, ARROW, cl=10), {})
    _consume_a_charge(engine)
    assert engine.state.actors[ME].temporary_hp == PB


def test_storm_heart_engine_gives_two_benefits_in_lightning_god_body():
    engine = _engine(_bundle(STORM_HEART, ARROW, GOD_BODY, cl=10), {})
    _use_on_self(engine, "Lightning-God Body")
    L._ready(engine)
    seen = _answers(engine, {"storm_heart": ("temp_hp", "move")})
    _consume_a_charge(engine)
    assert seen[0]["extension_choice"]["maximum_selections"] == 2 and engine.state.actors[ME].temporary_hp == PB


def test_true_lightning_god_mantle_replaces_the_body_cost_with_two_cp_and_inherits_its_state():
    engine = _engine(_bundle(STORM_HEART, ARROW, GOD_BODY, "TAL_LIGHTNING_TRUE_LIGHTNING_GOD_MANTLE", cl=15), {})
    me = engine.state.actors[ME]
    before = me.resources["resource:core.qi"]
    _use_on_self(engine, "Lightning-God Body + True Lightning-God Mantle")
    assert me.resources["resource:core.qi"] == before - 2  # instead of 1 CP, not 2 extra on top
    L._ready(engine)
    seen = _answers(engine, {"storm_heart": ("temp_hp", "move")})
    _consume_a_charge(engine)
    assert seen[0]["extension_choice"]["maximum_selections"] == 2 and me.temporary_hp == PB


def test_storm_heart_opportunity_disadvantage_is_used_up_by_the_next_opportunity_attack():
    engine = _engine(_bundle(STORM_HEART, ARROW, cl=10), {F1: (2, 6)})
    _answers(engine, {"storm_heart": ("oa_disadvantage",)})
    _consume_a_charge(engine)
    engine.state.actors[AN].reaction_available = False  # isolate the compiled foe's opportunity attack
    start = len(engine.events)
    _move(engine, ME, (3, 8))
    rolled = [e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == F1]
    assert rolled and rolled[0].payload["mode"] == "DISADVANTAGE"
    assert not any(c.condition_id == "condition:typed.storm_heart_oa_disadvantage" for c in engine.state.actors[ME].conditions.values())


# ------------------------------------------------------------------------------------------ lines dropped, not automated

FULL_NOW = {
    "lightning": ["TAL_LIGHTNING_CHARGED_NEEDLE", "TAL_LIGHTNING_CONDUCTIVE_STRIKE", "TAL_LIGHTNING_CRACKLING_ARROW", "TAL_LIGHTNING_LIGHTNING_LASH",
                  "TAL_LIGHTNING_MERIDIAN_STOPPING_SPARK", "TAL_LIGHTNING_STATIC_GUARD", "TAL_LIGHTNING_THUNDERCLAP_PALM"],
}


def test_abilities_whose_only_riders_were_notes_or_typed_lines_carry_no_gm_line_now():
    """Charged Needle, Conductive Strike, Crackling Arrow, Lightning Lash, Meridian-Stopping Spark and Static Guard carried notes
    about their own typing ("The previous typing ...", "is implemented in ..."), and Thunderclap Palm the stat lines and the
    Foundation Deafened its rows already run: none of them is a line the GM has to apply."""
    mechanics = L._mechanics()
    manual = {
        "TAL_LIGHTNING_CHARGED_NEEDLE": "already present before the hit",
        "TAL_LIGHTNING_CONDUCTIVE_STRIKE": "Conductive",
        "TAL_LIGHTNING_CRACKLING_ARROW": "ammunition or a thrown weapon",
        "TAL_LIGHTNING_LIGHTNING_LASH": "unattended object",
        "TAL_LIGHTNING_MERIDIAN_STOPPING_SPARK": "Game Master",
    }
    for sphere, keys in FULL_NOW.items():
        for key in keys:
            row = mechanics[key]
            if key in manual:
                # These are actual remaining printed delivery/eligibility
                # clauses, not the old notes about the implementation.
                assert row["coverage"] == "CORE_WITH_RIDERS"
                assert manual[key] in " ".join(row["riders"])
                assert not any(word in " ".join(row["riders"]) for word in ("implemented in", "previous typing", "combat/"))
            else:
                assert row["coverage"] == "FULL" and not row.get("riders"), (sphere, key, row.get("riders"))
