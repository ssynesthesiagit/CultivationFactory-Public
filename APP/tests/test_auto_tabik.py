"""Tabik Damu's kit (owner 2026-09-28: "we need to automate every aspect before another playtest"): the Dark sphere's area
talents in combat/ext/tabik_dark.py and combat/zones.py."""

from pathlib import Path

from combat import zones
from combat.ext import tabik_dark
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.tabik"


def _engine(talents, *, foe_at=(8, 6), seed="DARK"):
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.dark"],
                                     "automatic_sphere_component_record_ids": ["DARK_BASE_DARKNESS"],
                                     "learned_talent_record_ids": list(talents)}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    _turn(engine, ME)
    return engine, bundle


def _turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _end_turn(engine, actor_id):
    actor = engine.state.actors[actor_id]
    engine._append_event("TURN_ENDED", "system:turn", actor_id=actor_id, payload={})
    del actor


def _do(engine, name, *, at=None, actor=ME):
    candidate = next(c for c in engine.legal_candidates()
                     if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == name and c.actor_id == actor
                     and (at is None or (c.destination and (c.destination.x, c.destination.y) == at)))
    engine.execute_intent(ActionIntent(intent_id=f"{name}{engine.state.event_sequence}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _force_dc(engine, name, dc=40):
    for action in engine.action_catalog.values():
        if action.display_name.startswith(name) and action.owner_id == ME:
            typed = action.parameters["typed"]
            typed["numbers"] = {**typed["numbers"], "save_dc": dc}


def _darkness(engine):
    return next(zone for zone in engine.state.zones.values() if zone.active and zone.trigger_profile.get("name") == "Darkness")


def test_snagging_and_creeping_lethargy_are_shapes_not_riders_on_every_darkness():
    _engine_, bundle = _engine(["TAL_DARK_SNAGGING_DARKNESS", "TAL_DARK_CREEPING_LETHARGY"])
    darkness = next(row for row in bundle["action_catalog"] if row["display_name"] == "Darkness")
    assert not [effect for effect in darkness["parameters"]["typed"]["effects"] if effect.get("source_modifier")]
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert "Darkness + Creeping Lethargy" not in names and "Shape Darkness: Creeping Lethargy" in names


def test_clinging_darkness_rides_with_the_creature_it_is_centered_on():
    engine, bundle = _engine(["TAL_DARK_CLINGING_DARKNESS"])
    assert "Darkness + Clinging Darkness" in {row["display_name"] for row in bundle["action_catalog"]}
    engine.legal_candidates()
    _do(engine, "Darkness + Clinging Darkness", at=(3, 6))
    zone = _darkness(engine)
    assert zone.trigger_profile.get("anchor_id") == ME
    me = engine.state.actors[ME]
    start = me.position
    me.position = Position(x=5, y=6)
    zones.on_moved(engine, me, start, me.position)
    assert (zone.center.x, zone.center.y) == (5, 6)


def test_clinging_darkness_on_a_foe_that_fails_its_save_follows_it_until_it_saves():
    engine, _bundle = _engine(["TAL_DARK_CLINGING_DARKNESS"])
    _force_dc(engine, "Darkness")
    _do(engine, "Darkness + Clinging Darkness", at=(8, 6))
    zone = _darkness(engine)
    foe = engine.state.actors[AN]
    assert zone.trigger_profile.get("anchor_id") == AN
    assert any(c.condition_id == tabik_dark.CLINGS for c in foe.conditions.values())
    _force_dc(engine, "Darkness", dc=-20)
    zone.trigger_profile = {**zone.trigger_profile, "numbers": {**zone.trigger_profile["numbers"], "save_dc": -20}}
    tabik_dark.dark_turn_end(engine, foe)
    assert not zone.trigger_profile.get("anchor_id")


def test_rolling_blackout_moves_a_darkness_up_to_30_feet():
    engine, bundle = _engine(["TAL_DARK_ROLLING_BLACKOUT"])
    assert not any(getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == "Rolling Blackout: move Darkness" for c in engine.legal_candidates())
    _do(engine, "Darkness", at=(10, 6))
    offered = [c for c in engine.legal_candidates() if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == "Rolling Blackout: move Darkness"]
    assert offered and all(engine.grid.distance_ft(Position(x=10, y=6), c.destination) <= 30 for c in offered)
    _do(engine, "Rolling Blackout: move Darkness", at=(14, 6))
    assert (_darkness(engine).center.x, _darkness(engine).center.y) == (14, 6)


def test_directional_darkness_lets_those_outside_see_in_and_blinds_those_inside():
    engine, _bundle = _engine(["TAL_DARK_DIRECTIONAL_DARKNESS"])
    _do(engine, "Darkness", at=(8, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert zones.attack_mode(engine, me, foe) == "DISADVANTAGE"  # plain Darkness: can't see in
    _do(engine, "Augment Darkness: Directional Darkness")
    me.action_available = True
    _do(engine, "Darkness + Directional Darkness", at=(8, 6))
    # The same technique may be held twice (owner 2026-09-29), so the plain Darkness still stands over the same squares and
    # still hides the foe; take it down to see the directional one alone.
    plain = [zone for zone in zones.typed_zones(engine) if zone.owner_id == ME and not (zone.trigger_profile.get("visual") or {}).get("sees")]
    assert len(plain) == 1
    zones.remove(engine, plain[0], "TEST")
    assert zones.attack_mode(engine, me, foe) == "ADVANTAGE"  # sees in; the foe can't see out
    assert zones.attack_mode(engine, foe, me) == "DISADVANTAGE"


def test_creeping_lethargy_first_slows_then_puts_to_sleep_and_damage_wakes():
    engine, _bundle = _engine(["TAL_DARK_CREEPING_LETHARGY"])
    _do(engine, "Shape Darkness: Creeping Lethargy")
    _force_dc(engine, "Darkness")
    _do(engine, "Darkness", at=(8, 6))
    foe = engine.state.actors[AN]
    _turn(engine, AN)
    assert any(c.condition_id == tabik_dark.LETHARGIC for c in foe.conditions.values())
    assert not any(c.condition_id == tabik_dark.ASLEEP for c in foe.conditions.values())
    # Lethargic: after an Action, no Bonus Action (and the other way round)
    foe.action_available = False
    assert not any(c.actor_id == AN and engine.action_catalog.get(c.source_definition_id) is not None
                   and getattr(engine.action_catalog[c.source_definition_id].economy, "value", "") == "BONUS_ACTION" for c in engine.legal_candidates())
    engine.state.round_number += 1
    _turn(engine, AN)  # starts another turn inside, still lethargic: fails again
    assert any(c.condition_id == tabik_dark.ASLEEP for c in foe.conditions.values())
    engine._commit_damage(foe, 1, "FIRE", "test", ME, None, reaction_depth=0)
    assert not any(c.condition_id == tabik_dark.ASLEEP for c in foe.conditions.values())


def test_starting_a_turn_outside_ends_creeping_lethargy():
    engine, _bundle = _engine(["TAL_DARK_CREEPING_LETHARGY"])
    _do(engine, "Shape Darkness: Creeping Lethargy")
    _force_dc(engine, "Darkness")
    _do(engine, "Darkness", at=(8, 6))
    foe = engine.state.actors[AN]
    _turn(engine, AN)
    foe.position = Position(x=16, y=6)
    zones.sync_inside(engine, "test")
    _turn(engine, AN)
    assert not any(c.condition_id == tabik_dark.LETHARGIC for c in foe.conditions.values())


def test_hungry_darkness_bites_once_a_round():
    engine, _bundle = _engine(["TAL_DARK_HUNGRY_DARKNESS"])
    hungry = next(action for action in engine.action_catalog.values() if action.display_name == "Darkness")
    shape = hungry.parameters["typed"]["zone_spec"]["shapes"]["TAL_DARK_HUNGRY_DARKNESS"]
    assert shape["triggers"][0].get("per_round") is True


def test_fearful_darkness_frightens_until_the_creature_ends_a_turn_outside():
    engine, _bundle = _engine(["TAL_DARK_FEARFUL_DARKNESS"])
    _do(engine, "Shape Darkness: Fearful Darkness")
    _force_dc(engine, "Darkness")
    _do(engine, "Darkness", at=(8, 6))
    foe = engine.state.actors[AN]
    _turn(engine, AN)
    assert any(c.condition_id == tabik_dark.FRIGHTENED for c in foe.conditions.values())
    tabik_dark.dark_turn_end(engine, foe)  # ends its turn inside: still Frightened
    assert any(c.condition_id == tabik_dark.FRIGHTENED for c in foe.conditions.values())
    foe.position = Position(x=16, y=6)
    tabik_dark.dark_turn_end(engine, foe)
    assert not any(c.condition_id == tabik_dark.FRIGHTENED for c in foe.conditions.values())


def test_dark_slaughter_is_a_passive_row():
    _engine_, bundle = _engine(["TAL_DARK_DARK_SLAUGHTER"])
    rows = [row for row in bundle["typed_passives"] if row.get("block") == "dark_slaughter"]
    assert rows and rows[0]["dice_by_cl"][1] == [5, 10, 1, 8]
    assert "Dark Slaughter" not in bundle["diagnostics"]["skipped"]["passive"]


# ------------------------------------------------------------------------------------------------ Scoundrel
from combat.ext import tabik_scoundrel  # noqa: E402

SCOUNDREL = ["TAL_SCOUNDREL_DIRTY_TRICK", "TAL_SCOUNDREL_STEAL", "TAL_SCOUNDREL_TWIST_THE_KNIFE", "TAL_SCOUNDREL_FOCUSING_THIEVERY",
             "TAL_SCOUNDREL_CUT_AND_RUN", "TAL_SCOUNDREL_FILTHY_DISTRACTION"]


def _thief(sleight=40, talents=SCOUNDREL):
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.scoundrel"], "learned_talent_record_ids": list(talents)}}
    bundle = compile_character(sheet, actor_id=ME)
    bundle["skills"] = {"Sleight of Hand": sleight}
    engine = Gate4ControllerEngine(ROOT, match_seed="THIEF", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    _turn(engine, ME)
    return engine, bundle


def test_dirty_trick_is_one_result_per_use_behind_a_scoundrel_check():
    _engine_, bundle = _thief()
    tricks = [row for row in bundle["action_catalog"] if row["display_name"].startswith("DIRTY TRICK")]
    assert {row["display_name"].split(": ")[1] for row in tricks} == {"Eyes Spoiled", "Ears Ringing", "Tangled Footwork", "Low Sweep", "Jammed Guard", "Open the Guard"}
    assert all(row["target_kind"] == "HOSTILE_ENTITY" and row["range_ft"] == 5 for row in tricks)
    blind = next(row for row in tricks if row["display_name"].endswith("Eyes Spoiled"))
    assert [effect["type"] for effect in blind["parameters"]["typed"]["effects"]] == ["scoundrel_check"]


def test_eyes_spoiled_blinds_until_the_start_of_the_thiefs_next_turn_and_twists_the_knife():
    engine, _bundle = _thief()
    _do(engine, "DIRTY TRICK: Eyes Spoiled")
    foe = engine.state.actors[AN]
    blinded = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.blinded"]
    assert blinded and blinded[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert any(e.event_type == "CHECK_ROLLED" and (e.payload or {}).get("success") for e in engine.events)
    assert any(e.event_type == "PASSIVE_TRIGGERED" and (e.payload or {}).get("trigger") == "Twist the Knife" for e in engine.events)


def test_a_failed_check_does_nothing():
    engine, _bundle = _thief(sleight=0)
    foe = engine.state.actors[AN]
    foe.saving_throws["STR"] = 60  # its Athletics (no sheet skills): the thief can't win
    _do(engine, "DIRTY TRICK: Low Sweep")
    assert not any(c.condition_id == "condition:typed.prone" for c in foe.conditions.values())


def test_tangled_footwork_halves_speed():
    engine, _bundle = _thief()
    foe = engine.state.actors[AN]
    before = engine._effective_speed(foe)
    _do(engine, "DIRTY TRICK: Tangled Footwork")
    assert engine._effective_speed(foe) == before // 2


def test_open_the_guard_gives_advantage_once_and_stops_opportunity_attacks():
    engine, _bundle = _thief(talents=[name for name in SCOUNDREL if name != "TAL_SCOUNDREL_TWIST_THE_KNIFE"])  # Twist's attack would use it
    _do(engine, "DIRTY TRICK: Open the Guard")
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert any(c.condition_id == tabik_scoundrel.EXPLOITED for c in foe.conditions.values())
    assert tabik_scoundrel.no_opportunity(engine, foe, me) is False
    assert engine._attack_mode(me, foe) == "ADVANTAGE"


def test_steal_takes_the_weapon_and_focusing_thievery_is_offered_after_a_success():
    engine, _bundle = _thief()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.resources[tabik_scoundrel.FOCUS] = 0 if tabik_scoundrel.FOCUS in me.resources else None
    names = lambda: {getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) for c in engine.legal_candidates() if c.actor_id == ME}  # noqa: E731
    assert "Focusing Thievery: regain Martial Focus" not in names()
    _do(engine, "STEAL")
    if tabik_scoundrel.FOCUS in me.resources:
        assert "Focusing Thievery: regain Martial Focus" in names()
    disarmed = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.disarmed"]
    assert not disarmed or disarmed[0].data.get("held_by") == ME


# ------------------------------------------------------------------------------------------------ Unmaking
def test_black_vein_palm_and_devouring_dregs_compile_as_unmaking_rows_and_choices():
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.unmaking"],
                                     "learned_talent_record_ids": ["TAL_UNMAKING_RUIN_CHANNEL", "TAL_UNMAKING_BLACK_VEIN_PALM", "TAL_UNMAKING_DEVOURING_DREGS",
                                                                   "TAL_UNMAKING_DISSOLVE_THE_SEAM"]}}
    bundle = compile_character(sheet, actor_id=ME)
    kinds = {row.get("kind") for row in bundle["typed_passives"] if row.get("block") == "unmaking"}
    assert {"black_vein_palm", "devouring_dregs"} <= kinds
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {"Black-Vein Palm: No Reactions", "Black-Vein Palm: No Healing", "Black-Vein Palm: Constitution Save Disadvantage"} <= names
    channel = next(row for row in bundle["action_catalog"] if row["display_name"] == "Ruin Channel")
    assert not [effect for effect in channel["parameters"]["typed"]["effects"] if effect.get("source_modifier")]
    seam = next(row for row in bundle["action_catalog"] if row["display_name"] == "Dissolve the Seam")
    assert not [effect for effect in seam["parameters"]["typed"]["effects"] if effect.get("type") == "damage"]


# ------------------------------------------------------------------------------------------------ Flowing River
from combat.ext import flowing_river  # noqa: E402

FOE = "actor:factory.foe"


def _river(talents, *, foe_talents=(), foe_spheres=()):
    me_sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
                "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.flowing_river"],
                                        "learned_talent_record_ids": ["TAL_FLOWING_RIVER_FLOWING_RESPONSE", *talents]}}
    foe_sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
                 "spheres_and_talents": {"sphere_record_ids": list(foe_spheres), "learned_talent_record_ids": list(foe_talents)}}
    mine, theirs = compile_character(me_sheet, actor_id=ME), compile_character(foe_sheet, actor_id=FOE)
    engine = Gate4ControllerEngine(ROOT, match_seed="RIVER", typed_bundles=(mine, theirs),
                                   roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    _turn(engine, FOE)
    return engine, mine


def _foe_attack(engine, bonus):
    attack = next(c for c in engine.legal_candidates() if c.actor_id == FOE and ".weapon." in c.source_definition_id
                  and (engine.action_catalog[c.source_definition_id].range_ft or 5) <= 5 and ME in (c.target_ids or ()))
    typed = engine.action_catalog[attack.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": bonus}
    attack_effect = next(e for e in typed["effects"] if e.get("type") == "attack")
    attack_effect["count"] = 1
    engine.execute_intent(ActionIntent(intent_id=f"atk{engine.state.event_sequence}", decision_id=attack.decision_id, candidate_id=attack.candidate_id,
                                       state_version=attack.state_version, actor_id=FOE, target_ids=attack.target_ids))


def test_flowing_response_is_one_reaction_that_raises_ac_for_the_attack_only():
    _engine_, bundle = _river(["TAL_FLOWING_RIVER_HAND_ON_THE_WRIST"])
    row = next(r for r in bundle["typed_reactions"] if r.get("name") == "Flowing Response")
    assert [e["type"] for e in row["effects"]] == ["flowing_yield_attack"] and row["kind"] == "attacked"


def test_a_missed_melee_attack_is_a_success_and_hand_on_the_wrist_follows():
    engine, _bundle = _river(["TAL_FLOWING_RIVER_HAND_ON_THE_WRIST"])
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    ac = me.armor_class + engine._ac_modifier(me)
    _foe_attack(engine, -40)
    assert any(e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == flowing_river.RESPONSE for e in engine.events)
    assert any(e.event_type == "PASSIVE_TRIGGERED" and (e.payload or {}).get("trigger") == "Flowing Response succeeds" for e in engine.events)
    assert any(c.condition_id == "condition:typed.reaction_denied" for c in foe.conditions.values())
    assert me.armor_class + engine._ac_modifier(me) == ac  # the +PB was for that attack only


def test_a_hit_is_no_success():
    engine, _bundle = _river(["TAL_FLOWING_RIVER_HAND_ON_THE_WRIST"])
    foe = engine.state.actors[FOE]
    _foe_attack(engine, 60)
    assert not any(c.condition_id == "condition:typed.reaction_denied" for c in foe.conditions.values())


def test_river_takes_the_spear_stops_opportunity_attacks_with_that_weapon():
    engine, _bundle = _river(["TAL_FLOWING_RIVER_RIVER_TAKES_THE_SPEAR"])
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    _foe_attack(engine, -40)
    assert any(c.condition_id == flowing_river.NO_OA for c in foe.conditions.values())
    assert flowing_river.spear_no_opportunity(engine, foe, me) is False


def test_yield_against_control_gives_advantage_on_the_shove_save():
    engine, _bundle = _river(["TAL_FLOWING_RIVER_HAND_ON_THE_WRIST"])
    me = engine.state.actors[ME]
    shove = next(c for c in engine.legal_candidates() if c.actor_id == FOE and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == "Shove: Prone")
    engine.execute_intent(ActionIntent(intent_id="shove", decision_id=shove.decision_id, candidate_id=shove.candidate_id,
                                       state_version=shove.state_version, actor_id=FOE, target_ids=shove.target_ids))
    assert any(e.event_type == "REACTION_WINDOW_OPENED" and (e.payload or {}).get("checkpoint") == "SAVE_PENDING" for e in engine.events)
    assert not me.reaction_available


def test_empty_bank_evasion_and_reed_in_storm_are_rows():
    _engine_, bundle = _river(["TAL_FLOWING_RIVER_EMPTY_BANK_EVASION", "TAL_FLOWING_RIVER_REED_IN_STORM"])
    kinds = {row.get("kind") for row in bundle["typed_passives"] if row.get("block") == "flowing_river"}
    assert {"empty_bank_evasion", "reed_in_storm"} <= kinds
    assert "Flowing Response: step away" in {row["display_name"] for row in bundle["action_catalog"]}


# ------------------------------------------------------------------------------------------------ Qi Cultivation Path
from combat.ext import qi_path  # noqa: E402

QI_FEATURES = ["tianxia.path.qi_cultivation.feature.golden_core_form", "tianxia.path.qi_cultivation.feature.domain_armament",
               "tianxia.path.qi_cultivation.feature.meridian_regulation"]


def _qi():
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}], "path_and_subpath": {"path_feature_record_ids": QI_FEATURES},
             "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="QI", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 9, "y": 6}}})
    return engine, bundle


def _names(engine):
    return {getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) for c in engine.legal_candidates() if c.actor_id == ME}


def test_golden_core_form_is_a_choice_not_free_qi_and_stable_recovers():
    engine, bundle = _qi()
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert "Golden Core Form: Stable Golden Core" in names and "Golden Core Reservoir" in names
    me = engine.state.actors[ME]
    me.resources[qi_path.QI] = 0
    me.turn_flags.pop("golden_core_initiative_round_done", None)  # as if the fight were just beginning
    _turn(engine, ME)
    assert me.resources[qi_path.QI] == me.proficiency_bonus  # "when Initiative is rolled": up to PB
    assert "Golden Core Reservoir" not in _names(engine)  # only with the Reservoir Form
    me.resources[qi_path.QI] = 1
    engine.state.round_number += 1
    _turn(engine, ME)
    assert me.resources[qi_path.QI] == 2  # +1 at the start of its turn while below PB


def test_reservoir_form_offers_the_bonus_action_once():
    engine, _bundle = _qi()
    _turn(engine, ME)
    engine.state.actors[ME].turns_started = 1  # its first turn: the Form may still be chosen
    _do(engine, "Golden Core Form: Golden Core Reservoir")
    assert "Golden Core Reservoir" in _names(engine)
    _do(engine, "Golden Core Reservoir")
    engine.state.actors[ME].bonus_action_available = True
    assert "Golden Core Reservoir" not in _names(engine)


def test_domain_armament_manifests_then_attacks_and_guards():
    engine, _bundle = _qi()
    _turn(engine, ME)
    assert "Domain Armament Attack" not in _names(engine)
    # "Initial Position: One unoccupied point within 30 feet": the table asks which point the Armament appears on.
    _do(engine, "Domain Armament: Manifest", at=(3, 7))
    me = engine.state.actors[ME]
    assert qi_path._place(me) == (3, 7)
    me.bonus_action_available = True
    assert "Domain Armament Attack" in _names(engine)  # the foe is 30 feet away
    _do(engine, "Domain Armament: Guard Mode")
    assert "Domain Armament Attack" not in _names(engine)
    # "At the end of your turn, designate one creature within 5 feet as protected": here its owner, who stands next
    # to the Armament (no longer substituted -- see tests/test_domain_armament_and_manifestation.py for the ally).
    qi_path.armament_guard(engine, me)
    assert any(m.target_field == "armor_class_vs_ranged" and m.value == 2 for m in me.modifiers.values())


# ------------------------------------------------------------------------------------------------ Shinobi / Ninpo Adept
from combat.ext import tabik_ninpo  # noqa: E402

NINPO = ["tianxia.subpath.qi.ninpo_adept.feature.shadow_step", "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil",
         "tianxia.subpath.qi.ninpo_adept.feature.hidden_strike", "tianxia.subpath.body.shinobi.feature.shadow_afterimage",
         "tianxia.subpath.body.shinobi.feature.pressure_point_strike"]


def _ninja():
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}], "path_and_subpath": {"path_feature_record_ids": NINPO},
             "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="NINJA", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 9, "y": 6}}})
    _turn(engine, ME)
    return engine, bundle


def test_smoke_veil_hides_others_but_not_its_maker():
    engine, _bundle = _ninja()
    _do(engine, "Smoke Veil", at=(9, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    smoke = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Smoke Veil")
    assert smoke.trigger_profile.get("owner_sees")
    assert zones.attack_mode(engine, me, foe) is None  # it sees the foe inside its own smoke
    assert zones.attack_mode(engine, foe, me) is None  # the foe inside sees out, and its maker sees into its own smoke
    offered = [c for c in engine.legal_candidates() if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == "Smoke Veil: move"]
    assert offered and all(engine.grid.distance_ft(smoke.center, c.destination) <= 15 for c in offered)


def test_shadow_step_needs_concealment_at_both_ends():
    engine, _bundle = _ninja()
    names = lambda: {getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) for c in engine.legal_candidates() if c.actor_id == ME}  # noqa: E731
    assert "Shadow Step" not in names()
    _do(engine, "Smoke Veil", at=(4, 6))  # smoke over itself
    engine.state.actors[ME].bonus_action_available = True  # Smoke Veil took this turn's Bonus Action
    steps = [c for c in engine.legal_candidates() if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == "Shadow Step"]
    from combat import motion
    assert steps and all(motion.obscured_at(engine, c.destination) for c in steps)


def test_hidden_strike_and_pressure_point_are_rows_and_the_afterimage_a_creature():
    _engine_, bundle = _ninja()
    kinds = {row.get("kind") for row in bundle["typed_passives"] if row.get("block") == "ninpo"}
    assert {"hidden_strike", "pressure_point"} <= kinds
    assert [s["actor_template"]["display_name"] for s in bundle.get("summons") or []] == ["Shadow Afterimage"]
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {"Shadow Exchange", "Pressure-Point Strike: off", "Hidden Strike: Misleading Impact"} <= names


# ------------------------------------------------------------------------------------------------ Ancient Desolate Sacred Body
def test_golden_sea_guard_reduces_by_twice_pb_plus_con_and_rebuke_is_a_choice():
    from combat import typed_reactions

    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}], "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []},
             "foundation": {**(SHEET.get("foundation") or {})}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="SAINT", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    me = engine.state.actors[ME]
    row = {"feature_id": "x", "numbers": {"pb": 4, "cl": 10, "key_mod": 3}, "ability_mods": {"CON": 3}}
    assert typed_reactions._generic_amount(engine, me, row, {"type": "damage_modifier", "formula": "2*pb+con"}) == 11
    assert typed_reactions._generic_amount(engine, me, row, {"type": "damage_modifier", "formula": "pb+nonsense"}) == 0


def test_court_of_the_crawling_fever_is_a_moving_aura_that_tests_at_turn_start():
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": ["tianxia.talent.disease.court_of_the_crawling_fever"]}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="FEVER", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 6, "y": 6}}})
    _turn(engine, ME)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.resources["resource:core.qi"] = 10
    hp = foe.current_hp
    _force_dc(engine, "Court of the Crawling Fever")
    _do(engine, "Court of the Crawling Fever")
    assert foe.current_hp == hp  # nothing on the cast itself
    court = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Court of the Crawling Fever")
    assert court.trigger_profile.get("follows_owner") and court.trigger_profile["triggers"][-1]["on"] == ["start"]
    court.trigger_profile["numbers"]["save_dc"] = 40
    _turn(engine, AN)
    assert foe.current_hp < hp


def test_shadow_slick_trips_a_creature_moving_more_than_half_its_speed_through():
    engine, _bundle = _engine(["TAL_DARK_SHADOW_SLICK"], foe_at=(12, 6))
    _do(engine, "Shape Darkness: Shadow Slick")
    _force_dc(engine, "Darkness")
    _do(engine, "Darkness", at=(8, 6))
    foe = engine.state.actors[AN]
    start = foe.position
    foe.position = Position(x=7, y=6)  # 25 feet, into the Darkness (more than half its Speed)
    zones.on_moved(engine, foe, start, foe.position)
    assert any(c.condition_id == "condition:typed.prone" for c in foe.conditions.values())
