"""Summoned creatures and companions (owner 2026-09-27: "might as well do the summons too, ill want to test it anyway"):
each is a fighter of its own on its summoner's side, acting right after it; commanded by a Bonus Action, it takes one
action, otherwise it Dodges and its turn passes by itself (combat/summons.py, combat/rules/summons.json).
"""

from pathlib import Path

from combat import summons, typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, CandidateKind, Position

ROOT = Path(__file__).resolve().parents[1]
OWNER = "actor:factory.summoner"


def _sheet(talents: list[str], pb: int = 4, cl: int = 10) -> dict:
    return {
        "identity": {"proficiency_bonus": pb, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": "WIS"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 30}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 8,
        },
        "spheres_and_talents": {"learned_talent_record_ids": talents},
    }


def _engine(talents: list[str], **plan) -> Gate2Engine:
    bundle = compile_character(_sheet(talents), actor_id=OWNER, summon_plan=plan or None)
    engine = Gate2Engine(ROOT, match_seed="SUMMONS", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                                       "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 12, "y": 6}}})
    return engine


def _turn_of(engine: Gate2Engine, actor_id: str) -> None:
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _use(engine: Gate2Engine, actor_id: str, action_suffix: str) -> None:
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id.endswith(action_suffix))
    engine.execute_intent(ActionIntent(intent_id=f"use-{action_suffix}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def test_servants_are_on_the_summoners_side_right_after_it():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"])
    servants = summons.owned_by(engine, OWNER, "corpse_servant")
    assert len(servants) == 4  # the Death Control Limit is the Proficiency Bonus
    order = engine.state.initiative_order
    assert order[order.index(OWNER) + 1: order.index(OWNER) + 5] == [s.entity_id for s in servants]
    owner = engine.state.actors[OWNER]
    for servant in servants:
        assert servant.team_id == owner.team_id and not servant.primary_combatant and servant.active
        assert engine.grid.distance_ft(servant.position, owner.position) <= 10
        assert servant.armor_class == 16 and servant.maximum_hp == 52  # 12 + PB; 5 x CL + key modifier


def test_an_uncommanded_servant_dodges_and_a_commanded_one_attacks():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    servant = summons.owned_by(engine, OWNER)[0]
    _turn_of(engine, OWNER)
    engine.end_turn()  # no command: the servant Dodges and its turn passes by itself
    assert engine.state.current_actor_id != servant.entity_id
    assert any(c.condition_id == "condition:core.dodge" for c in servant.conditions.values())
    _turn_of(engine, OWNER)
    _use(engine, OWNER, ".command.death")  # Commanding Death Servants: one command for every Death servant (rider lane C14)
    engine.end_turn()
    assert engine.state.current_actor_id == servant.entity_id and servant.action_available and not servant.bonus_action_available
    assert any(c.kind == CandidateKind.MOVE for c in engine.legal_candidates())


def test_the_painted_beast_is_called_and_leaves_with_concentration():
    engine = _engine(["tianxia.talent.ink.painted_beast"])
    beast = summons.owned_by(engine, OWNER, "painted_beast")[0]
    assert not beast.active and beast.summon["status"] == "waiting"
    owner = engine.state.actors[OWNER]
    _turn_of(engine, OWNER)
    _use(engine, OWNER, ".tianxia.talent.ink.painted_beast")
    assert beast.active and beast.summon["status"] == "present" and beast.current_hp == beast.maximum_hp
    assert engine.grid.distance_ft(beast.position, owner.position) <= 30
    assert owner.armor_class == 14  # the beast's AC is no longer given to Ning Kai
    owner.action_available = True
    assert not any(c.source_definition_id.endswith(".ink.painted_beast") for c in engine.legal_candidates())  # already out
    assert any(c.source_definition_id.endswith(".command.painted_beast") for c in engine.legal_candidates())
    engine._end_concentration(owner, "TEST")
    assert not beast.active and beast.summon["status"] == "dismissed"


def test_a_destroyed_servant_leaves_and_the_fight_goes_on():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    servant = summons.owned_by(engine, OWNER)[0]
    engine._defeat(servant, "test")
    assert servant.summon["status"] == "destroyed" and engine.state.terminal_result is None
    _turn_of(engine, OWNER)
    assert not any(c.source_definition_id.endswith(".command.death") for c in engine.legal_candidates())


def test_servants_are_immune_to_fear_and_the_lantern_is_not_armour():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT", "TAL_DEATH_GHOST_LANTERN"], corpse_servant=1)
    servant = summons.owned_by(engine, OWNER, "corpse_servant")[0]
    assert typed_executor.condition_immune(engine, servant, "frightened")
    lantern = next(a for a in engine.action_catalog.values() if a.source_definition_id.endswith(".TAL_DEATH_GHOST_LANTERN"))
    assert lantern.parameters["typed"]["effects"] == [{"type": "summon", "group": "ghost_lantern"}]
    assert lantern.parameters.get("inert")  # nothing to fight with: left to a player, not the AI


def test_a_formation_below_half_uses_its_weaker_assault():
    engine = _engine(["tianxia.talent.ink.ten_thousand_illustrated_soldiers"], painted_formation=1)
    formation = summons.owned_by(engine, OWNER)[0]
    foe = engine.state.actors[AN]
    foe.position = Position(x=formation.position.x + 1, y=formation.position.y)
    engine.state.current_actor_id = formation.entity_id
    formation.action_available = True
    attacks = lambda: {c.source_definition_id.rsplit(".", 1)[-1] for c in engine.legal_candidates() if "attack" in c.source_definition_id}  # noqa: E731
    assert attacks() == {"attack0"}
    formation.current_hp = formation.maximum_hp // 2
    assert attacks() == {"weak"}


def test_minute_summon_duration_is_evented_and_expires_on_its_tenth_round():
    bundle = compile_character(_sheet(["tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation"], cl=10),
                               actor_id=OWNER)
    engine = Gate4ControllerEngine(ROOT, match_seed="SUMMON-DURATION", typed_bundles=(bundle,),
        roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                      "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 12, "y": 6}}})
    guard = summons.owned_by(engine, OWNER, "bone_guard")[0]
    owner = engine.state.actors[OWNER]
    summons.summon(engine, owner, "bone_guard", "test:bone_guard")
    duration = next(c for c in guard.conditions.values() if c.source_definition_id == "system:combat.summon_duration")
    assert duration.expires_on.startswith("START_OF_SLOT_AT:")
    from combat.ext import effect_durations
    expiry_round = int(duration.expires_on.split(":")[1])
    engine.state.round_number = expiry_round - 1
    effect_durations.sweep(engine, guard, "START_OF_TURN")
    assert guard.active  # the body is present through the round immediately before this turn starts
    engine.state.round_number = expiry_round
    effect_durations.sweep(engine, guard, "START_OF_TURN")
    assert not guard.active
    assert any(e.event_type == "SUMMON_DISMISSED" and e.payload.get("reason") == "DURATION_ENDED" for e in engine.events)


def test_talisman_spirit_duration_is_present_before_and_gone_at_expiry_turn_start():
    bundle = compile_character(_sheet(["tianxia.talent.talismans.talisman_spirit"], cl=10), actor_id=OWNER)
    engine = Gate4ControllerEngine(ROOT, match_seed="TALISMAN-SPIRIT-DURATION", typed_bundles=(bundle,),
        roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                      "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 12, "y": 6}}})
    spirit = summons.owned_by(engine, OWNER, "talisman_spirit")[0]
    owner = engine.state.actors[OWNER]
    expiry_round = engine.state.round_number + 10  # printed one minute = ten rounds
    expiry_slot = engine.state.current_slot_index
    summons.summon(engine, owner, "talisman_spirit", "test:talisman_spirit")
    duration = next(c for c in spirit.conditions.values() if c.source_definition_id == "system:combat.summon_duration")
    from combat.ext import effect_durations
    assert duration.expires_on == f"START_OF_SLOT_AT:{expiry_round}:{expiry_slot}"
    engine.state.round_number = expiry_round - 1
    effect_durations.sweep(engine, spirit, "START_OF_TURN")
    assert spirit.active
    engine.state.round_number = expiry_round
    effect_durations.sweep(engine, spirit, "START_OF_TURN")
    assert not spirit.active


def test_companions_inherit_the_owners_ask_me_reaction_policy():
    bundle = compile_character(_sheet(["tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation"], cl=10),
                               actor_id=OWNER, reaction_plan={"ask": True})
    guard = next(row for row in bundle["summons"] if row["summon"]["group"] == "bone_guard")
    assert any(row["name"] == "Guard the Sovereign" and row["ask"] for row in guard["typed_reactions"])


def test_bone_guard_uses_owner_save_totals_including_recorded_proficiency():
    owner = _sheet(["tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation"], cl=10)
    recorded = {"STR": 6, "DEX": 7, "CON": 8, "INT": 5, "WIS": 6, "CHA": 4}
    owner["ability_scores_and_statistics"]["saving_throws"] = recorded
    bundle = compile_character(owner, actor_id=OWNER)
    guard = next(row for row in bundle["summons"] if row["summon"]["group"] == "bone_guard")
    assert bundle["actor_template"]["saving_throws"] == recorded
    assert guard["actor_template"]["saving_throws"] == recorded


def test_data_driven_uncommanded_movement_follows_owner_before_dodge():
    bundle = compile_character(_sheet(["tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation"], cl=10),
                               actor_id=OWNER)
    engine = Gate4ControllerEngine(ROOT, match_seed="SUMMON-FOLLOW", typed_bundles=(bundle,),
        roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                      "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 19, "y": 6}}})
    owner = engine.state.actors[OWNER]
    guard = summons.owned_by(engine, OWNER, "bone_guard")[0]
    summons.summon(engine, owner, "bone_guard", "test:bone_guard")
    owner.position = Position(x=14, y=6)
    before = engine._distance_actor_to_actor(owner, guard)
    engine.state.current_actor_id = guard.entity_id
    guard.movement_remaining_ft = guard.speed_ft
    engine._append_event("TURN_STARTED", "system:test.turn", actor_id=guard.entity_id, payload={"round": 2, "slot": 1})
    assert engine._distance_actor_to_actor(owner, guard) == before
    assert not any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == guard.entity_id for e in engine.events)
    summons.on_turn_start(engine, guard)
    after = engine._distance_actor_to_actor(owner, guard)
    assert after < before and after <= 30
    assert any(row.condition_id == "condition:core.dodge" for row in guard.conditions.values())
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == guard.entity_id for e in engine.events)


def test_follow_policy_stays_when_frightened_from_approaching_owner():
    bundle = compile_character(_sheet(["tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation"], cl=10),
                               actor_id=OWNER)
    engine = Gate4ControllerEngine(ROOT, match_seed="SUMMON-FOLLOW-FRIGHTENED", typed_bundles=(bundle,),
        roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                      "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 19, "y": 6}}})
    owner, foe = engine.state.actors[OWNER], engine.state.actors[AN]
    guard = summons.owned_by(engine, OWNER, "bone_guard")[0]
    summons.summon(engine, owner, "bone_guard", "test:bone_guard")
    guard.position, owner.position, foe.position = (Position(x=5, y=6), Position(x=15, y=6), Position(x=20, y=6))
    engine._apply_condition(guard, "condition:typed.frightened", "system:test.frightened", foe.entity_id,
                            expires_on="UNTIL_REMOVED")
    engine.state.current_actor_id = guard.entity_id
    guard.movement_remaining_ft = guard.speed_ft
    before = guard.position
    from combat.ext.companion_movement import move_toward_owner
    move_toward_owner(engine, guard, owner, 30)
    assert guard.position == before
    assert not any(event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == guard.entity_id
                   for event in engine.events)


def test_a_tamer_gets_a_beast_that_needs_no_command():
    assert compile_character(_sheet(["tianxia.talent.beastmastery.mounted_offense"]), actor_id=OWNER)["summons"] == []  # a Rider only
    engine = _engine(["TAL_BEASTMASTERY_BEAST_TAMER"], beasts=["tiger"])
    beast = summons.owned_by(engine, OWNER)[0]
    assert beast.display_name == "Tiger" and beast.maximum_hp == 37 and beast.summon["command"] == "free"
    assert not any(".command." in a.source_definition_id for a in engine.action_catalog.values() if a.owner_id == OWNER)
    _turn_of(engine, OWNER)
    engine.end_turn()  # "Giving ordinary commands requires no Action": its own turn, unasked
    assert engine.state.current_actor_id == beast.entity_id and beast.action_available


def test_a_guarding_servant_takes_the_edge_off_a_blow_beside_it():
    from combat import typed_reactions

    engine = _engine(["TAL_DEATH_CORPSE_SERVANT", "TAL_DEATH_DEATHLESS_GUARD"], corpse_servant=1)
    servant, owner = summons.owned_by(engine, OWNER)[0], engine.state.actors[OWNER]
    servant.position = Position(x=owner.position.x, y=owner.position.y + 1)
    foe = engine.state.actors[AN]
    assert typed_reactions._offer_ally_damaged(engine, owner, foe, 20, 0, AN) == 20  # not Guarding: no reaction
    engine.state.current_actor_id = servant.entity_id
    servant.action_available = True
    _use(engine, servant.entity_id, ".guard")
    reduced = typed_reactions._offer_ally_damaged(engine, owner, foe, 20, 0, AN)
    assert 20 - 12 <= reduced <= 20 - 5 and not servant.reaction_available  # 1d8 + PB at CL 10


def test_the_owner_picks_how_many_come_and_which_beasts(tmp_path):
    import pytest

    from combat.tabletop import ButtonStore, TabletopError

    talents = ["TAL_BEASTMASTERY_BEAST_TAMER", "TAL_DEATH_CORPSE_SERVANT"]
    options = compile_character(_sheet(talents), actor_id=OWNER)["summon_options"]
    store, pid = ButtonStore(tmp_path), "0123abcd-0000"
    saved = store.save_summons(pid, {"counts": {"corpse_servant": 2}, "beasts": ["tiger", "hawk"]}, options)["summons"]
    assert store.save_summons(pid, {"counts": {"corpse_servant": 1}}, options)["summons"]["beasts"] == ["tiger", "hawk"]  # kept
    bundle = compile_character(_sheet(talents), actor_id=OWNER, summon_plan=saved)
    assert sorted(row["actor_template"]["display_name"] for row in bundle["summons"]) == ["Corpse Servant 1", "Corpse Servant 2", "Hawk", "Tiger"]
    for bad in ({"counts": {"corpse_servant": 5}}, {"counts": {"painted_beast": 1}}, {"beasts": ["dragon"]}):
        with pytest.raises(TabletopError):
            store.save_summons(pid, bad, options)


def test_the_bone_guard_and_specter_use_the_summoners_numbers():
    engine = _engine(["tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation",
                      "tianxia.tradition.spirit.soul_warden_necromancer.feature.raise_specter"])
    guard = summons.owned_by(engine, OWNER, "bone_guard")[0]
    specter = summons.owned_by(engine, OWNER, "predatory_specter")[0]
    assert guard.armor_class == 18 and guard.maximum_hp == 50 and not guard.active  # 14 + PB, 5 x CL, called by its action
    assert specter.armor_class == 15 and specter.maximum_hp == 24  # the Cultivation save DC, 6 x PB
    strike = engine.action_catalog[guard.action_ids[0]].parameters["typed"]["weapon"]["damage"]
    assert strike == {"count": 2, "sides": 8, "modifier": 2}  # 2d8 + Constitution modifier


def test_a_command_is_worth_what_the_whole_group_does():
    """Fight audit 2026-09-29: four Corpse Servants on one command were valued as one, so a single Bonded Spirit's command
    always won and the servants Dodged all fight."""
    bundle = compile_character(_sheet(["TAL_DEATH_CORPSE_SERVANT"]), actor_id=OWNER)
    each = [creature["summon"]["expected_damage"] for creature in bundle["summons"] if creature["summon"]["group"] == "corpse_servant"]
    command = next(a for a in bundle["action_catalog"] if a["display_name"] == "Command Death servants")  # one command for all Death servants
    assert len(each) == 4 and command["parameters"]["expected_damage"] == sum(each) > each[0]
