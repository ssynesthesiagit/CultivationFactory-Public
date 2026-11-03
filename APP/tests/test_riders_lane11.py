"""Real-character regressions for lane 11's printed combat riders."""

from pathlib import Path

import pytest

from combat import zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.r11"
PREFIX = "tianxia.subpath.qi."
FLOWING = PREFIX + "abyssal_depths_cultivator.feature.flowing_evasion"
MOON = PREFIX + "abyssal_depths_cultivator.feature.moon_s_pull"
CONCENTRATION_IDS = (
    MOON,
    'tianxia.subpath.qi.bell_tower_cultivator.feature.ninefold_heavenly_bell',
    'tianxia.subpath.qi.black_sea_leviathan_womb.feature.gate_of_the_inner_sea',
    'tianxia.subpath.qi.black_sea_leviathan_womb.feature.world_beneath_the_black_sea',
    'tianxia.subpath.qi.calligraphy_cultivator.feature.character_of_binding',
    'tianxia.subpath.qi.cloud_walker.feature.cloud_step',
    'tianxia.subpath.qi.cremation_cinder_heart.feature.cremate_heaven_and_earth',
    'tianxia.subpath.qi.cremation_cinder_heart.feature.cremation_prison',
    'tianxia.subpath.qi.cultivator_of_seals.feature.chains_of_qi',
    'tianxia.subpath.qi.cultivator_of_seals.feature.heaven_sealing_edict',
    'tianxia.subpath.qi.cultivator_of_seals.feature.prison_of_law',
    'tianxia.subpath.qi.dragon_vein_geomancer.feature.imperial_dragon_vein',
    'tianxia.subpath.qi.dust_cultivator.feature.dust_cloud',
    'tianxia.subpath.qi.dust_cultivator.feature.sandstorm_field',
    'tianxia.subpath.qi.emotion_cultivator.feature.weather_of_the_heart',
    'tianxia.subpath.qi.five_elements_cultivator.feature.world_cleansing_cycle',
    'tianxia.subpath.qi.formation_breaking_halberd_cultivator.feature.field_of_the_broken_array',
    'tianxia.subpath.qi.formation_breaking_halberd_cultivator.feature.ten_armies_collapse',
    'tianxia.subpath.qi.go_stone_cultivator.feature.heavenly_board_of_encirclement',
    'tianxia.subpath.qi.harvest_cultivator.feature.orchard_field',
    'tianxia.subpath.qi.harvest_cultivator.feature.ten_thousand_seed_ascension',
    'tianxia.subpath.qi.hearthfire_cultivator.feature.flame_that_welcomes_all',
    'tianxia.subpath.qi.heaven_splitting_conceptual_severance.feature.divide_heaven_and_earth',
    'tianxia.subpath.qi.heaven_thunder_storm_soul.feature.tribulation_cloud_core',
    'tianxia.subpath.qi.incense_cultivator.feature.palace_of_ten_thousand_scents',
    'tianxia.subpath.qi.iron_cloth_cultivator.feature.silken_prison',
    'tianxia.subpath.qi.iron_cloth_cultivator.feature.thousand_ribbons',
    'tianxia.subpath.qi.karma_thread_cultivator.feature.chain_of_cause_and_effect',
    'tianxia.subpath.qi.karma_thread_cultivator.feature.heavenly_ripening_of_karma',
    'tianxia.subpath.qi.kiln_cultivator.feature.imperial_kiln_array',
    'tianxia.subpath.qi.kite_cultivator.feature.festival_of_the_heavenly_sky',
    'tianxia.subpath.qi.kite_cultivator.feature.signal_formation',
    'tianxia.subpath.qi.lantern_keeper.feature.ten_thousand_lantern_road',
    'tianxia.subpath.qi.mantra_cultivator.feature.great_mantra',
    'tianxia.subpath.qi.mantra_cultivator.feature.mantra_of_silence',
    'tianxia.subpath.qi.mason_cultivator.feature.raise_the_imperial_bastion',
    'tianxia.subpath.qi.nightmare_dream_qi_cultivator.feature.shared_nightmare_prison',
    'tianxia.subpath.qi.ninpo_adept.feature.vanishing_technique',
    'tianxia.subpath.qi.oath_ledger_cultivator.feature.battlefield_covenant',
    'tianxia.subpath.qi.oath_ledger_cultivator.feature.heaven_as_witness',
    'tianxia.subpath.qi.onmyoji.feature.kami_invitation',
    'tianxia.subpath.qi.onmyoji.feature.onmyodo_grandmaster',
    'tianxia.subpath.qi.orbiting_shield_warden.feature.nine_shields_seal_heaven',
    'tianxia.subpath.qi.painting_cultivator.feature.painted_prison',
    'tianxia.subpath.qi.paper_cultivator.feature.paper_heaven',
    'tianxia.subpath.qi.poison_cultivator.feature.toxic_cloud',
    'tianxia.subpath.qi.puzzle_cultivator.feature.maze_of_the_mind',
    'tianxia.subpath.qi.puzzle_cultivator.feature.palace_of_the_final_riddle',
    'tianxia.subpath.qi.puzzle_cultivator.feature.puzzle_wall',
    'tianxia.subpath.qi.raincaller_cultivator.feature.call_rain',
    'tianxia.subpath.qi.raincaller_cultivator.feature.monsoon_sovereign',
    'tianxia.subpath.qi.raincaller_cultivator.feature.monsoon_wall',
    'tianxia.subpath.qi.riverway_cultivator.feature.imperial_river_field',
    'tianxia.subpath.qi.riverway_cultivator.feature.moonlit_ferry',
    'tianxia.subpath.qi.samsara_wheel_cultivator.feature.ten_thousand_lives_domain',
    'tianxia.subpath.qi.sound_cultivator.feature.song_of_fear',
    'tianxia.subpath.qi.ten_thousand_sword_array_cultivator.feature.ten_thousand_swords_return_to_origin',
    'tianxia.subpath.qi.venomous_poison_cultivator.feature.plague_of_one_hundred_meridians',
    'tianxia.subpath.qi.void_touched_cultivator.feature.hollow_field',
    'tianxia.subpath.qi.yin_yang_cultivator.feature.taiji_field',
)


def _sheet(mid, *, dc=50, cl=20):
    return {**SHEET, "identity": {**SHEET["identity"], "cultivation_level": cl},
             "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"], "technique_save_dc": dc},
             "spheres_and_talents": {}, "path_and_subpath": {"path_feature_record_ids": [mid]}}


def _fight(mid, *, dc=50, cl=20):
    bundle = compile_character(_sheet(mid, dc=dc, cl=cl), actor_id=ME)
    engine = Gate4ControllerEngine(
        ROOT, match_seed="RIDERS11", typed_bundles=(bundle,),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 8, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for actor in engine.state.actors.values():
        actor.maximum_hp = 10000
        actor.current_hp = 10000
    # Keep this concentration-lifetime test independent of damage-save luck.
    engine.state.actors[ME].saving_throws["CON"] = 1000
    return engine


def _cast(engine, mid, *, at=None, option=None):
    actions = {key for key, action in engine.action_catalog.items()
               if (action.parameters.get("typed") or {}).get("source") == mid
               and (option is None or (action.parameters.get("typed") or {}).get("option_label") == option)}
    candidates = [c for c in engine.legal_candidates() if c.source_definition_id in actions]
    if at is not None:
        candidates = [c for c in candidates if c.destination == at]
    assert candidates, f"No legal candidate for {mid}"
    candidate = candidates[0]
    engine.execute_intent(ActionIntent(intent_id="r11-cast", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    return candidate.source_definition_id


def _flowing_attack(*, owns=True, defense=None, seed="R11-FLOWING"):
    """Real compiled Dao attack; only AC/HP and optional defense are fixtures."""
    attacker_id = "actor:factory.r11.attacker"
    defender_sheet = _sheet(FLOWING)
    if not owns:
        defender_sheet["path_and_subpath"] = {"path_feature_record_ids": []}
    attacker_sheet = {**_sheet(FLOWING),
        "path_and_subpath": {"path_feature_record_ids": []},
        "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}]}}]}
    bundles = (compile_character(defender_sheet, actor_id=ME),
               compile_character(attacker_sheet, actor_id=attacker_id))
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
        roster_setup={"primary_actor_ids": [ME, attacker_id],
            "team_by_actor": {ME: "team:a", attacker_id: "team:b"},
            "starting_positions": {ME: {"x": 3, "y": 6}, attacker_id: {"x": 4, "y": 6}}})
    engine.typed_control_modes = {ME: "LOCAL_AUTO", attacker_id: "LOCAL_AUTO"}
    engine.state.current_slot_index = engine.state.initiative_order.index(attacker_id)
    engine.state.current_actor_id = attacker_id
    engine._system_start_turn()
    defender = engine.state.actors[ME]
    defender.maximum_hp = 1000
    defender.current_hp = 1000
    defender.armor_class = -100  # every roll except natural 1 hits
    if defense:
        engine._add_modifier(defender, "r11-defense-fixture", "damage_" + defense,
                             "SET", "SLASHING", "SELF", expires_on="START_OF_SELF_NEXT_TURN")
    before_qi = defender.resources["resource:core.qi"]
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.startswith("Dao") and c.target_ids == (ME,))
    engine.execute_intent(ActionIntent(intent_id="r11-flowing-attack", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=attacker_id, target_ids=candidate.target_ids, destination=candidate.destination))
    rolls = [e for e in engine.events if e.event_type == "ATTACK_ROLLED"]
    packets = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids]
    assert len(rolls) == len(packets) == 1
    return engine, rolls[0], packets[0], before_qi


@pytest.mark.parametrize("seed,critical", [("R11-FLOWING", False), ("R11-FLOWING-21", True)])
@pytest.mark.parametrize("defense", [None, "resistance", "vulnerability", "immunity"])
def test_flowing_evasion_locked_checkpoint_reproduction(defense, seed, critical):
    """Lock round 4 resolves the old blocker at the post-defense checkpoint."""
    engine, roll, packet, before_qi = _flowing_attack(defense=defense, seed=seed)
    _, control_roll, control_packet, _ = _flowing_attack(owns=False, defense=defense, seed=seed)
    assert roll.payload == control_roll.payload
    assert packet.payload["rolled_or_pending_damage"] == control_packet.payload["rolled_or_pending_damage"]
    assert (roll.payload["natural_result"] == 20) is critical
    pending = control_packet.payload["reduced_to"]
    raw = control_packet.payload["rolled_or_pending_damage"]
    assert raw > 0
    assert pending == {None: raw, "resistance": raw // 2,
                       "vulnerability": raw * 2, "immunity": 0}[defense]
    # Round 21 lock round 4: one native reaction halves defended damage,
    # including critical hits; immunity offers no damage to evade.
    assert packet.payload["reduced_to"] == pending // 2
    defender = engine.state.actors[ME]
    assert before_qi - defender.resources["resource:core.qi"] == (2 if pending else 0)
    assert defender.current_hp == 1000 - pending // 2
    assert defender.reaction_available is (not bool(pending))
    resolved = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == FLOWING]
    assert len(resolved) == (1 if pending else 0)
    if resolved:
        assert resolved[0].payload["checkpoint"] == "POST_DEFENSE_ATTACK_DAMAGE"
        assert resolved[0].payload["attack_roll_id"] == roll.payload["roll_id"]
        assert resolved[0].payload["critical"] is critical
        assert resolved[0].payload["damage_before"] == pending
        assert resolved[0].payload["damage_after"] == pending // 2


# Round 21 lock round 4 supplies the requested seam; this contract must pass.
@pytest.mark.parametrize("defense,seed", [
    (None, "R11-FLOWING"), ("resistance", "R11-FLOWING"),
    ("vulnerability", "R11-FLOWING"), ("immunity", "R11-FLOWING"),
    (None, "R11-FLOWING-21"), ("resistance", "R11-FLOWING-21"),
    ("vulnerability", "R11-FLOWING-21")])
def test_flowing_evasion_halves_only_positive_post_defense_attack_damage(defense, seed):
    """Printed-rule contract now implemented by lock round 4's owned plug-in."""
    engine, _, packet, before_qi = _flowing_attack(defense=defense, seed=seed)
    _, _, control_packet, _ = _flowing_attack(owns=False, defense=defense, seed=seed)
    pending = control_packet.payload["reduced_to"]
    assert packet.payload["reduced_to"] == pending // 2
    defender = engine.state.actors[ME]
    assert before_qi - defender.resources["resource:core.qi"] == (2 if pending else 0)



@pytest.mark.parametrize("mid", CONCENTRATION_IDS, ids=lambda mid: mid.removeprefix(PREFIX))
def test_printed_concentration_starts_and_ending_it_removes_its_zones(mid):
    engine = _fight(mid)
    source = _cast(engine, mid)
    actor = engine.state.actors[ME]
    assert actor.concentration is not None
    assert actor.concentration.source_definition_id == source
    own_zones = [z for z in zones.typed_zones(engine) if z.source_definition_id == source]
    assert all(z.concentration_link for z in own_zones)
    engine._end_concentration(actor, "r11-test")
    assert actor.concentration is None
    assert not [z for z in zones.typed_zones(engine) if z.source_definition_id == source]


@pytest.mark.parametrize("dc,distance,speed_delta", [(50, 15, -10), (-40, 5, 0)])
def test_moons_pull_waits_for_entry_and_pulls_once_toward_the_field(dc, distance, speed_delta):
    engine = _fight(MOON, dc=dc)
    foe = engine.state.actors[AN]
    start = foe.position
    _cast(engine, MOON, at=Position(x=4, y=6))
    assert foe.position == start  # creation is not a printed trigger
    [zone] = zones.typed_zones(engine)
    assert zone.trigger_profile["difficult"] == "hostile"
    assert (5, 6) in zones.difficult_cells(engine, foe)
    assert (5, 6) not in zones.difficult_cells(engine, engine.state.actors[ME])
    zones.on_moved(engine, foe, Position(x=15, y=6), start)
    assert foe.position == Position(x=8 - distance // 5, y=6)
    assert sum(m.value for m in foe.modifiers.values() if m.target_field == "speed_ft") == speed_delta
    after = foe.position
    zones.on_turn_start(engine, foe)
    assert foe.position == after  # enter/start share the once-per-turn gate


def _moon_riders(engine, source):
    return [event.payload["rider"] for event in engine.events
            if event.event_type == "GM_RIDER" and event.source_definition_id == source]


def test_moons_pull_enforced_range_and_cost_are_not_gm_riders():
    engine = _fight(MOON)
    actor = engine.state.actors[ME]
    actions = {key for key, action in engine.action_catalog.items()
               if (action.parameters.get("typed") or {}).get("source") == MOON}
    candidates = [c for c in engine.legal_candidates() if c.source_definition_id in actions]
    assert candidates
    assert all(engine._distance_actor_to_cell(actor, c.destination) <= 60 for c in candidates)
    boundary = next(c.destination for c in candidates
                    if engine._distance_actor_to_cell(actor, c.destination) == 60)
    # A clear, in-bounds point farther away verifies the rejection boundary.
    beyond = Position(x=engine.grid.width - 1, y=engine.grid.height - 1)
    assert engine._distance_actor_to_cell(actor, beyond) > 60
    assert beyond not in {c.destination for c in candidates}
    before = actor.resources["resource:core.qi"]
    source = _cast(engine, MOON, at=boundary)
    assert actor.resources["resource:core.qi"] == before - 5
    assert not actor.bonus_action_available and actor.action_available
    assert actor.concentration.source_definition_id == source
    riders = _moon_riders(engine, source)
    assert riders  # Armament, Tidal Path, suppression and vertical area remain pending.
    assert not any(line.startswith("Range:") or "Cost: 5 Qi" in line for line in riders)


def test_moons_pull_enforced_minute_is_not_a_gm_rider():
    engine = _fight(MOON)
    # Keep the foe outside this field so turn progression tests only duration.
    source = _cast(engine, MOON, at=Position(x=0, y=6))
    [zone] = zones.typed_zones(engine)
    assert zone.duration_rounds == 10 and zone.concentration_link
    created = zone.created_round
    while engine.state.round_number - created < 10:
        assert engine.state.zones[zone.zone_id].active
        _take_named(engine, "End turn")
    # Expiry happens at the source's turn start, regardless of initiative order.
    if engine.state.current_actor_id != ME:
        assert engine.state.zones[zone.zone_id].active
        _take_named(engine, "End turn")
    assert not zones.typed_zones(engine)
    assert not engine.state.zones[zone.zone_id].active
    assert any(e.event_type == "ZONE_REMOVED" and e.payload.get("reason") == "DURATION_ENDED"
               for e in engine.events)
    assert not any("Duration: 1 minute" in line for line in _moon_riders(engine, source))


def test_moons_pull_enforced_headers_survive_table_commit_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="R11-MOON-HEADERS",
        typed_bundles=(compile_character(_sheet(MOON), actor_id=ME),),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 8, "y": 6}}})
    def commit(candidate):
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"r11-moon-saved-{candidate.state_version}", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit(next(c for c in session.engine.legal_candidates() if c.display_name == "End turn"))
    before = session.engine.state.actors[ME].resources["resource:core.qi"]
    candidate = next(c for c in session.engine.legal_candidates()
                     if c.source_definition_id in session.engine.action_catalog and
                     c.destination == Position(x=0, y=6) and
                     (session.engine.action_catalog[c.source_definition_id].parameters.get("typed") or {}).get("source") == MOON)
    source = candidate.source_definition_id
    commit(candidate)
    reloaded = persistence.load_match(session.match_id)
    engine = reloaded.engine
    actor = engine.state.actors[ME]
    [zone] = zones.typed_zones(engine)
    assert actor.resources["resource:core.qi"] == before - 5
    assert not actor.bonus_action_available
    assert actor.concentration.source_definition_id == source
    assert zone.duration_rounds == 10 and zone.concentration_link
    assert engine.action_catalog[source].range_ft == 60
    riders = _moon_riders(engine, source)
    assert riders
    assert not any(line.startswith("Range:") or "Duration: 1 minute" in line for line in riders)
    assert reloaded.verify()["status"] == "PASS"


@pytest.mark.parametrize("formula,base", [("Flame Pill", 6), ("Frost Pill", 4), ("Venom Pill", 4), ("Impact Pill", 4)])
@pytest.mark.parametrize("cl", [16, 17])
@pytest.mark.parametrize("dc", [50, -40], ids=["failed-save", "successful-save"])
def test_explosive_pill_adds_two_d6_at_cl17_on_both_save_branches(formula, base, cl, dc):
    mid = PREFIX + "alchemical_cultivator.feature.explosive_pill"
    engine = _fight(mid, cl=cl, dc=dc)
    before_qi = engine.state.actors[ME].resources["resource:core.qi"]
    source = _cast(engine, mid, option=formula, at=Position(x=8, y=6))
    rolls = [e.payload for e in engine.events if e.event_type == "DAMAGE_ROLLED" and e.source_definition_id == source]
    assert rolls
    count = base + (2 if cl >= 17 else 0)
    assert all(roll["expression"] == f"{count}d6+0" and len(roll["dice"]) == count for roll in rolls)
    assert engine.state.actors[ME].resources["resource:core.qi"] == before_qi - 3


DEEP = PREFIX + "abyssal_depths_cultivator.feature.deep_s_embrace"


@pytest.mark.parametrize("existing,expected", [(0, 60), (30, 60), (120, 150)])
def test_deep_darkvision_runs_without_a_duplicate_gm_rider(existing, expected):
    from types import SimpleNamespace
    from combat import senses

    engine = _fight(DEEP)
    actor, foe = engine.state.actors[ME], engine.state.actors[AN]
    if existing:
        # An already active sense is supported runtime state, independent of
        # Deep's Embrace; this tests the printed additive branch without relying
        # on Tidal Resilience's separate environment-dependent grant.
        engine._apply_condition(actor, senses.SENSE, "test:existing-darkvision", ME,
                                expires_on="UNTIL_REMOVED",
                                data={"sense": "darkvision", "range_ft": existing})
    assert senses.of(engine, actor)["darkvision"]["range_ft"] == expected
    assert "darkvision" not in senses.of(engine, foe)
    darkness = SimpleNamespace(trigger_profile={"name": "Darkness", "visual": {"darkness": True}})
    foe.position = Position(x=3 + expected // 5, y=6)
    assert senses.pierces(engine, darkness, actor, foe)
    foe.position = Position(x=4 + expected // 5, y=6)
    assert not senses.pierces(engine, darkness, actor, foe)
    # Keep the real activation in a legal scene. The passive sense requires no
    # Liquid Body activation, Qi, concentration or new condition marker.
    foe.position = Position(x=8, y=6)
    source = _cast(engine, DEEP)
    riders = [e.payload["rider"] for e in engine.events
              if e.event_type == "GM_RIDER" and e.source_definition_id == source]
    assert riders  # Other, genuinely unautomated lines still reach the GM.
    assert all("darkvision" not in line.lower() for line in riders)
    assert senses.of(engine, actor)["darkvision"]["range_ft"] == expected


def test_deep_darkvision_bundle_survives_table_commit_reload(tmp_path):
    from combat import senses
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="R11-DEEP-SIGHT",
        typed_bundles=(compile_character(_sheet(DEEP), actor_id=ME),),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 8, "y": 6}}})
    # Commit an ordinary table action; senses live in the persisted bundle and
    # must be present before the Bonus Action is ever used.
    _take_named(session.engine, "End turn")
    reloaded = persistence.load_match(session.match_id)
    assert senses.of(reloaded.engine, reloaded.engine.state.actors[ME])["darkvision"] == {"range_ft": 60}
    assert reloaded.verify()["status"] == "PASS"


def _net_fight(talent="tianxia.talent.trap.net", level=20, *, caught=True, old=False):
    from tests.test_sys_placed_effects import _pick

    sheet = _sheet(MOON, cl=level, dc=1)
    sheet["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.trap"],
                                    "learned_talent_record_ids": [talent]}
    bundle = compile_character(_sheet(DEEP), actor_id=ME)
    if old:
        for action in bundle["action_catalog"]:
            for row in action.get("parameters", {}).get("typed", {}).get("effects", []):
                row.pop("net_holds", None)
    engine = Gate4ControllerEngine(
        ROOT, match_seed="R11-NET", typed_bundles=(bundle, compile_character(sheet, actor_id=AN)),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    engine.state.current_actor_id = AN
    engine._system_start_turn()
    _pick(engine, "Trap form: Noose" if talent == "TAL_TRAP_NOOSE" else "Trap form: Net (Snare use)", actor=AN)
    _pick(engine, "Set Trap", at=(3, 5), actor=AN)
    engine.end_turn()
    assert engine.state.current_actor_id == ME
    engine.state.actors[ME].saving_throws["DEX"] = -100
    if caught:
        _pick(engine, "Move to 3,5", at=(3, 5), actor=ME)
    return engine


@pytest.mark.parametrize("talent", ["tianxia.talent.trap.net", "TAL_TRAP_NOOSE"])
@pytest.mark.parametrize("level", [20, 21])
def test_liquid_body_net_escape_advantage_ends_only_the_linked_restraint(talent, level):
    from tests.test_sys_placed_effects import _pick
    from combat.ext.trap import NETTED

    engine = _net_fight(talent, level)
    actor = engine.state.actors[ME]
    marker = next(c for c in actor.conditions.values() if c.condition_id == NETTED)
    hold = next(iid for iid, c in actor.conditions.items() if c.condition_id == "condition:typed.restrained"
                and c.source_actor_id == marker.source_actor_id and c.source_definition_id == marker.source_definition_id)
    unrelated = _grip(engine, kind="restrained", physical=False)
    _cast(engine, DEEP)
    events = _pick(engine, "Escape the net", actor=ME)
    roll = next(e.payload for e in events if e.event_type == "CHECK_ROLLED")
    assert roll["actor"]["mode"] == "ADVANTAGE" and roll["success"]
    assert hold not in actor.conditions and not any(c.condition_id == NETTED for c in actor.conditions.values())
    assert unrelated <= set(actor.conditions)
    assert not actor.action_available and actor.reaction_available


@pytest.mark.parametrize("talent", ["tianxia.talent.trap.net", "TAL_TRAP_NOOSE"])
def test_liquid_body_activation_ends_one_lower_net_and_its_marker(talent):
    from combat.ext.trap import NETTED

    engine = _net_fight(talent, 19)
    actor = engine.state.actors[ME]
    held = {iid for iid, c in actor.conditions.items() if c.condition_id in {NETTED, "condition:typed.restrained"}}
    unrelated = _grip(engine, kind="restrained", physical=False)
    _cast(engine, DEEP)
    assert not held & set(actor.conditions) and unrelated <= set(actor.conditions)
    assert "Escape the net" not in {c.display_name for c in engine.legal_candidates()}


@pytest.mark.parametrize("talent", ["tianxia.talent.trap.net", "TAL_TRAP_NOOSE"])
@pytest.mark.parametrize("level", [19, 20, 21])
def test_liquid_body_prevents_only_lower_net_attempts(talent, level):
    from tests.test_sys_placed_effects import _pick
    from combat.ext.trap import NETTED

    engine = _net_fight(talent, level, caught=False)
    _cast(engine, DEEP)
    _pick(engine, "Move to 3,5", at=(3, 5), actor=ME)
    actor = engine.state.actors[ME]
    assert any(c.condition_id == "condition:typed.restrained" for c in actor.conditions.values()) == (level >= 20)
    assert any(c.condition_id == NETTED for c in actor.conditions.values()) == (level >= 20)


def test_liquid_body_old_net_bundle_retains_normal_escape_and_untracked_marker():
    from tests.test_sys_placed_effects import _pick
    from combat.ext.trap import NETTED

    engine = _net_fight(old=True)
    assert "hold_id" not in next(c.data for c in engine.state.actors[ME].conditions.values() if c.condition_id == NETTED)
    _cast(engine, DEEP)
    events = _pick(engine, "Escape the net", actor=ME)
    assert next(e.payload["actor"]["mode"] for e in events if e.event_type == "CHECK_ROLLED") == "NORMAL"


def test_liquid_body_expired_net_escape_loses_advantage_but_keeps_its_exact_pair():
    from tests.test_sys_placed_effects import _pick

    engine = _net_fight()
    unrelated = _grip(engine, kind="restrained", physical=False)
    _cast(engine, DEEP)
    engine.end_turn()
    engine.end_turn()
    events = _pick(engine, "Escape the net", actor=ME)
    assert next(e.payload["actor"]["mode"] for e in events if e.event_type == "CHECK_ROLLED") == "NORMAL"
    assert unrelated <= set(engine.state.actors[ME].conditions)


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_liquid_body_lower_net_service_choice_ends_one_hold(mode, tmp_path):
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService, _ReactionRequired
    from combat.ext.trap import NETTED

    service = CombatService(ROOT, tmp_path)
    engine = _net_fight(level=19)
    actor = engine.state.actors[ME]
    marker_id, marker = next((iid, c) for iid, c in actor.conditions.items() if c.condition_id == NETTED)
    hold_id = marker.data["hold_id"]
    grapple = next(iter(_grip(engine)))
    session = service.persistence.create_match(match_seed="R11-NET-PREVIEW", typed_bundles=())
    session.engine = engine
    action_ids = {key for key, action in engine.action_catalog.items()
                  if action.parameters.get("typed", {}).get("source") == DEEP}
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id in action_ids)
    intent = ActionIntent(intent_id="r11-net-preview", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=ME, target_ids=candidate.target_ids)
    metadata = {"participant_control_modes": {ME: mode, AN: "LOCAL_AUTO"}}
    before = engine.state.model_dump(mode="json")
    answers = ()
    if mode == "MANUAL":
        with pytest.raises(_ReactionRequired) as paused:
            service._run_preview(session, metadata, intent, ())
        context = paused.value.context
        assert set(context.legal_option_ids) == {hold_id, grapple}  # net marker is not a second hold
        assert "Deep’s Embrace" in context.choice_trigger["prompt"] and actor.display_name in context.choice_trigger["prompt"]
        answers = (ReactionDecision(checkpoint=context.checkpoint, reactor_id=ME,
                                   reaction_source_id=context.reaction_source_id, selection="USE", option_ids=(hold_id,)),)
    preview = service._run_preview(session, metadata, intent, answers)
    selected = preview["resolved_reactions"][0]["option_ids"][0]
    assert selected in {hold_id, grapple}
    removed = {e["payload"].get("instance_id") for e in preview["events"] if e["event_type"] == "CONDITION_REMOVED"}
    assert (hold_id in removed and marker_id in removed and grapple not in removed) if selected == hold_id else (
        grapple in removed and hold_id not in removed and marker_id not in removed)
    assert engine.state.model_dump(mode="json") == before


def test_liquid_body_net_pair_and_escape_survive_table_commit_reload_replay(tmp_path):
    from combat.ext.abyssal_depths import LIQUID
    from combat.ext.trap import NETTED
    from combat.gate4_persistence import Gate4Persistence

    sheet = _sheet(DEEP)
    sheet["ability_scores_and_statistics"]["abilities"] = [
        {**row, **({"score": 100, "modifier": 49} if row["ability"] == "STR" else {})}
        for row in sheet["ability_scores_and_statistics"]["abilities"]]
    trapper = _sheet(MOON, cl=20, dc=30)
    trapper["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.trap"],
                                     "learned_talent_record_ids": ["tianxia.talent.trap.net"]}
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(
        match_seed="R11-NET-SAVED", typed_bundles=(compile_character(sheet, actor_id=ME), compile_character(trapper, actor_id=AN)),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})

    def take(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"r11-net-saved-{candidate.state_version}", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != AN:
        take("End turn")
    take("Trap form: Net (Snare use)")
    take("Set Trap at 3,5")
    take("End turn")
    take("Move to 3,5")
    take("Deep’s Embrace")
    loaded = persistence.load_match(session.match_id)
    actor = loaded.engine.state.actors[ME]
    marker = next(c for c in actor.conditions.values() if c.condition_id == NETTED)
    assert isinstance(marker.data["hold_id"], str) and marker.data["hold_id"] in actor.conditions
    assert next(c.data["net_holds"] for c in actor.conditions.values() if c.condition_id == LIQUID) == 1
    assert loaded.verify()["status"] == "PASS"
    session = loaded
    take("Escape the net")
    reloaded = persistence.load_match(session.match_id)
    assert not any(c.condition_id in {NETTED, "condition:typed.restrained"} for c in reloaded.engine.state.actors[ME].conditions.values())
    assert reloaded.engine.state == session.engine.state
    assert reloaded.verify()["status"] == "PASS"


@pytest.mark.parametrize("choose_new", [False, True])
def test_liquid_body_multiple_nets_choose_and_release_one_source_exact_pair(choose_new):
    from combat.ext import trap
    from combat.gate2_runtime_models import ReactionDecision
    from combat.typed_executor import Context, block_condition
    from tests.test_sys_placed_effects import _pick

    engine = _net_fight()
    actor = engine.state.actors[ME]
    old_id, old = next((iid, c) for iid, c in actor.conditions.items() if c.condition_id == trap.NETTED)
    action = engine.action_catalog[old.source_definition_id]
    # A second source packet from the real compiled Set Trap action: tests repeated holds
    # without pretending a Restrained actor can walk into a second snare.
    before = set(actor.conditions)
    ctx = Context(engine, engine.state.actors[AN], action, None,
                  {**action.parameters["typed"], "source": "trap:fixture"}, [actor], actor,
                  {"_trap_existing_holds": {ME: before}})
    block_condition(ctx, {"type": "condition", "condition": "restrained", "applies_to": "target", "until_escape": True,
                          "hold_kind": "ordinary_physical"})
    trap.trap_netted(ctx, {})
    new_id, new = next((iid, c) for iid, c in actor.conditions.items() if iid not in before and c.condition_id == trap.NETTED)
    _cast(engine, DEEP)
    chosen_id, chosen = (new_id, new) if choose_new else (old_id, old)
    kept_id, kept = (old_id, old) if choose_new else (new_id, new)

    def answer(request):
        assert set(request["legal_option_ids"]) == {old_id, new_id}
        assert "Net / Noose" in request["choice_trigger"]["prompt"] and "Escape the net" in request["choice_trigger"]["prompt"]
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=ME,
                                reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=(chosen_id,)), None

    engine.set_reaction_provider(answer)
    _pick(engine, "Escape the net", actor=ME)
    assert chosen_id not in actor.conditions and chosen.data["hold_id"] not in actor.conditions
    assert kept_id in actor.conditions and kept.data["hold_id"] in actor.conditions


def _take_named(engine, name):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=f"r11-pin-{candidate.state_version}",
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination))


def _pin_bundles(level=19, old=False, legacy=False):
    sheet = _sheet(DEEP)
    if old:
        sheet = _sheet(MOON)  # character without Deep's Embrace is a legacy control
    wrestler = _sheet(MOON, cl=level, dc=50)
    wrestler["ability_scores_and_statistics"]["abilities"] = [
        {**row, **({"score": 100, "modifier": 49} if row["ability"] == "STR" else {})}
        for row in wrestler["ability_scores_and_statistics"]["abilities"]]
    wrestler["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.wrestling"],
        "learned_talent_record_ids": ["TAL_WRESTLING_PIN_2"]}
    bundle = compile_character(sheet, actor_id=ME)
    if legacy:
        # A saved Deep's Embrace bundle from before this opt-in was added.
        for action in bundle["action_catalog"]:
            typed = action["parameters"].get("typed", {})
            if typed.get("source") == DEEP:
                for row in typed.get("effects", []):
                    row.pop("linked_holds", None)
    return (bundle, compile_character(wrestler, actor_id=AN))


def _pin_fight(level=19, old=False, legacy=False):
    engine = Gate4ControllerEngine(ROOT, match_seed="R11-PIN", typed_bundles=_pin_bundles(level, old, legacy),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    engine.state.current_actor_id = AN
    engine._system_start_turn()
    # Force the actual compiled Grapple and Pin saves to fail, independently of seed.
    engine.state.actors[ME].saving_throws.update(STR=-100, DEX=-100)
    _take_named(engine, "Grapple")
    while engine.state.current_actor_id == AN:
        _take_named(engine, "End turn")
    _take_named(engine, "End turn")
    return engine


@pytest.mark.parametrize("level", [19, 20, 21])
def test_liquid_body_pin_prevents_only_lower_restraint_without_initial_save_advantage(level):
    engine = _pin_fight(level)
    # Activate during the holder's intervening turn; Pin then happens before expiry.
    if level < 20:
        # A separate nonphysical grip survives activation, leaving a legal Pin target.
        # The initial compiled ordinary Grapple must end; it cannot support this test.
        _grip(engine, physical=False)
    _take_named(engine, "End turn")
    _cast(engine, DEEP)
    _take_named(engine, "End turn")
    _take_named(engine, "Pin")
    restraints = [c for c in engine.state.actors[ME].conditions.values() if c.condition_id == "condition:typed.restrained"]
    assert bool(restraints) == (level >= 20)
    rolls = [e.payload for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == ME]
    assert rolls[-1]["mode"] == "NORMAL"
    if restraints:
        assert restraints[0].data["parent_hold"] in engine.state.actors[ME].conditions


@pytest.mark.parametrize("end", ["pin", "grapple"])
def test_liquid_body_pin_end_one_choice_preserves_other_holds(end):
    from combat.gate2_runtime_models import ReactionDecision

    engine = _pin_fight()
    _take_named(engine, "Pin")
    actor = engine.state.actors[ME]
    pin = next(k for k,c in actor.conditions.items() if c.condition_id == "condition:typed.restrained")
    parent = actor.conditions[pin].data["parent_hold"]
    other = next(iter(_grip(engine, physical=False)))
    _take_named(engine, "End turn")
    seen = []
    def answer(request):
        seen.append(request)
        assert set(request["legal_option_ids"]) == {pin, parent}
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=ME,
            reaction_source_id=request["reaction_source_id"], selection="USE",
            option_ids=(pin if end == "pin" else parent,)), None
    engine.set_reaction_provider(answer)
    _cast(engine, DEEP)
    assert len(seen) == 1 and "Deep’s Embrace" in seen[0]["choice_trigger"]["prompt"]
    assert pin not in actor.conditions and other in actor.conditions
    assert (parent in actor.conditions) == (end == "pin")


@pytest.mark.parametrize("level", [20, 21])
def test_liquid_body_pin_escape_parent_has_advantage_and_releases_only_its_pin(level):
    engine = _pin_fight(level)
    _take_named(engine, "Pin")
    actor = engine.state.actors[ME]
    pin = next(k for k,c in actor.conditions.items() if c.condition_id == "condition:typed.restrained")
    parent = actor.conditions[pin].data["parent_hold"]
    other = next(iter(_grip(engine, physical=False)))
    _take_named(engine, "End turn")
    _cast(engine, DEEP)
    # Guaranteed success for the actual offered escape Action.
    escape = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Escape grapple")
    escape.parameters["typed"]["numbers"]["escape_bonus"] = 100
    _take_named(engine, "Escape grapple")
    check = next(e.payload for e in reversed(engine.events) if e.event_type == "CHECK_ROLLED")
    assert check["actor"]["mode"] == "ADVANTAGE"
    assert parent not in actor.conditions and pin not in actor.conditions and other in actor.conditions


def test_liquid_body_pin_unowned_control_keeps_legacy_condition():
    engine = _pin_fight(old=True)
    _take_named(engine, "Pin")
    restrained = next(c for c in engine.state.actors[ME].conditions.values() if c.condition_id == "condition:typed.restrained")
    assert "parent_hold" not in restrained.data
    assert restrained.expires_on == "END_OF_HOLDER_NEXT_TURN"


def test_liquid_body_pin_prior_saved_bundle_does_not_track_or_end_the_pin():
    from combat.ext.abyssal_depths import LIQUID

    engine = _pin_fight(legacy=True)
    _take_named(engine, "Pin")
    actor = engine.state.actors[ME]
    pin = next(c for c in actor.conditions.values() if c.condition_id == "condition:typed.restrained")
    assert "parent_hold" not in pin.data and pin.expires_on == "END_OF_HOLDER_NEXT_TURN"
    _take_named(engine, "End turn")
    _cast(engine, DEEP)
    assert pin.instance_id in actor.conditions  # the old bundle ends the Grapple only
    assert not any(c.condition_id == "condition:typed.grappled" for c in actor.conditions.values())
    assert "linked_holds" not in next(c.data for c in actor.conditions.values() if c.condition_id == LIQUID)


def test_liquid_body_pin_link_survives_benefit_expiry_without_lingering_advantage():
    from combat.ext.abyssal_depths import LIQUID

    engine = _pin_fight(20)
    _take_named(engine, "Pin")
    actor = engine.state.actors[ME]
    pin = next(c for c in actor.conditions.values() if c.condition_id == "condition:typed.restrained")
    parent = pin.data["parent_hold"]
    _take_named(engine, "End turn")
    _cast(engine, DEEP)
    _take_named(engine, "End turn")
    _take_named(engine, "End turn")
    assert not any(c.condition_id == LIQUID for c in actor.conditions.values())
    assert pin.instance_id in actor.conditions and parent in actor.conditions
    escape = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Escape grapple")
    escape.parameters["typed"]["numbers"]["escape_bonus"] = 100
    _take_named(engine, "Escape grapple")
    check = next(e.payload for e in reversed(engine.events) if e.event_type == "CHECK_ROLLED")
    assert check["actor"]["mode"] == "NORMAL"
    assert parent not in actor.conditions and pin.instance_id not in actor.conditions


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_liquid_body_pin_service_choice_ends_only_the_selected_hold(mode, tmp_path):
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService, _ReactionRequired

    service = CombatService(ROOT, tmp_path)
    engine = _pin_fight()
    _take_named(engine, "Pin")
    _take_named(engine, "End turn")
    actor = engine.state.actors[ME]
    pin = next(k for k,c in actor.conditions.items() if c.condition_id == "condition:typed.restrained")
    parent = actor.conditions[pin].data["parent_hold"]
    session = service.persistence.create_match(match_seed="R11-PIN-PREVIEW", typed_bundles=())
    session.engine = engine
    c = next(c for c in engine.legal_candidates() if c.display_name == "Deep’s Embrace")
    intent = ActionIntent(intent_id="r11-pin-preview", decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=ME, target_ids=c.target_ids)
    metadata = {"participant_control_modes": {ME: mode, AN: "LOCAL_AUTO"}}
    before = engine.state.model_dump(mode="json")
    answers = ()
    if mode == "MANUAL":
        with pytest.raises(_ReactionRequired) as paused:
            service._run_preview(session, metadata, intent, ())
        context = paused.value.context
        assert set(context.legal_option_ids) == {pin, parent}
        assert "Deep’s Embrace" in context.choice_trigger["prompt"] and actor.display_name in context.choice_trigger["prompt"]
        answers = (ReactionDecision(checkpoint=context.checkpoint, reactor_id=ME,
            reaction_source_id=context.reaction_source_id, selection="USE", option_ids=(pin,)),)
    preview = service._run_preview(session, metadata, intent, answers)
    selected = preview["resolved_reactions"][0]["option_ids"][0]
    assert selected in {parent, pin}
    removed = {e["payload"].get("instance_id") for e in preview["events"] if e["event_type"] == "CONDITION_REMOVED"}
    assert pin in removed and (parent in removed) == (selected == parent)
    assert engine.state.model_dump(mode="json") == before


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_liquid_body_pin_multiple_parent_choice_is_source_exact(mode, tmp_path):
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService, _ReactionRequired

    engine = _pin_fight(20)
    actor = engine.state.actors[ME]
    first = next(k for k,c in actor.conditions.items() if c.condition_id == "condition:typed.grappled")
    second = next(iter(_grip(engine)))  # second actual compiled Grapple packet, same source actor
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(match_seed="R11-PIN-PARENTS", typed_bundles=())
    session.engine = engine
    c = next(c for c in engine.legal_candidates() if c.display_name == "Pin")
    intent = ActionIntent(intent_id="r11-pin-parents", decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=AN, target_ids=c.target_ids)
    metadata = {"participant_control_modes": {ME: "LOCAL_AUTO", AN: mode}}
    before = engine.state.model_dump(mode="json")
    answers = ()
    if mode == "MANUAL":
        with pytest.raises(_ReactionRequired) as paused:
            service._run_preview(session, metadata, intent, ())
        context = paused.value.context
        assert set(context.legal_option_ids) == {first, second}
        assert "Pin" in context.choice_trigger["prompt"] and actor.display_name in context.choice_trigger["prompt"]
        labels = context.choice_trigger["labels"]
        assert len(set(labels.values())) == 2
        assert all(iid not in label for iid, label in labels.items())
        answers = (ReactionDecision(checkpoint=context.checkpoint, reactor_id=AN,
            reaction_source_id=context.reaction_source_id, selection="USE", option_ids=(second,)),)
    preview = service._run_preview(session, metadata, intent, answers)
    selected = preview["resolved_reactions"][0]["option_ids"][0]
    assert selected in {first, second}
    if mode == "MANUAL":
        assert selected == second
    assert engine.state.model_dump(mode="json") == before


def test_liquid_body_pin_link_and_release_survive_table_commit_reload_replay(tmp_path):
    from combat.ext.abyssal_depths import LIQUID
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="R11-PIN-SAVED", typed_bundles=_pin_bundles(20),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    def take(name):
        c = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.mechanical.execute_intent(ActionIntent(intent_id=f"r11-pin-saved-{c.state_version}",
            decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
            actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination))
    while session.engine.state.current_actor_id != AN:
        take("End turn")
    take("Grapple")
    take("End turn")
    take("End turn")
    take("Pin")
    take("End turn")
    take("Deep’s Embrace")
    session = persistence.load_match(session.match_id)
    actor = session.engine.state.actors[ME]
    pin = next(c for c in actor.conditions.values() if c.condition_id == "condition:typed.restrained")
    assert isinstance(pin.data["parent_hold"], str) and pin.data["parent_hold"] in actor.conditions
    assert pin.expires_on == "UNTIL_REMOVED"
    assert next(c.data["linked_holds"] for c in actor.conditions.values() if c.condition_id == LIQUID) == 1
    assert session.verify()["status"] == "PASS"
    take("End turn")
    # Pin lasts past the victim's next turn, unlike the old fallback duration.
    assert pin.instance_id in session.engine.state.actors[ME].conditions
    take("Release grapple")
    reloaded = persistence.load_match(session.match_id)
    assert not any(c.condition_id in {"condition:typed.restrained", "condition:typed.grappled"}
                   for c in reloaded.engine.state.actors[ME].conditions.values())
    assert reloaded.engine.state == session.engine.state
    assert reloaded.verify()["status"] == "PASS"


def _hold_fight(level=19):
    engine = Gate4ControllerEngine(
        ROOT, match_seed="R11-HOLDS", typed_bundles=(compile_character(_sheet(DEEP), actor_id=ME),
                                                     compile_character(_sheet(MOON, cl=level), actor_id=AN)),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _grip(engine, *, kind="grappled", physical=True, level=None, save=None):
    """A core compiled Grapple, or a controlled source packet testing explicit hold classification."""
    from combat.typed_executor import Context, block_condition

    action = next(a for a in engine.action_catalog.values() if a.owner_id == AN
                  and (a.parameters.get("typed") or {}).get("unarmed_option") == "grapple")
    typed = action.parameters["typed"]
    row = {"type": "condition", "condition": kind, "applies_to": "target", "until_escape": True}
    if not physical or kind != "grappled" or level is not None:
        typed = {**typed, "unarmed_option": None, "numbers": {**typed["numbers"], **({"cl": level} if level is not None else {})},
                 "effects": [{**row, **({"hold_kind": "ordinary_physical"} if physical else {})}]}
        row = typed["effects"][0]
        action = action.model_copy(update={"source_definition_id": action.source_definition_id + f".{kind}.{physical}.{level}",
                                           "parameters": {"typed": typed}})
        engine.action_catalog[action.source_definition_id] = action
    actor, foe = engine.state.actors[ME], engine.state.actors[AN]
    intent = ActionIntent(intent_id="r11-hold", decision_id="fixture", candidate_id="fixture",
                          state_version=engine.state.state_version, actor_id=AN, target_ids=(ME,))
    before = set(actor.conditions)
    block_condition(Context(engine, foe, action, intent, typed, [actor], target=actor), row)
    added = set(actor.conditions) - before
    if save and added:
        # A source with printed repeat-save escape (as Living Painting uses) is a controlled packet.
        key = next(iter(added))
        actor.conditions[key] = actor.conditions[key].model_copy(update={"data": {**actor.conditions[key].data, "escape_save": save}})
    return added


@pytest.mark.parametrize("kind", ["grappled", "restrained"])
def test_liquid_body_player_chooses_exactly_one_lower_physical_hold(kind):
    from combat.gate2_runtime_models import ReactionDecision

    engine = _hold_fight()
    first = next(iter(_grip(engine)))
    second = next(iter(_grip(engine, kind=kind)))
    magical = next(iter(_grip(engine, physical=False)))
    equal = next(iter(_grip(engine, level=20)))
    actor = engine.state.actors[ME]
    seen = []

    def answer(request):
        seen.append(request)
        assert set(request["legal_option_ids"]) == {first, second}
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=ME,
                                reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=(second,)), None

    engine.set_reaction_provider(answer)
    _cast(engine, DEEP)
    assert len(seen) == 1
    assert "Deep’s Embrace" in seen[0]["choice_trigger"]["prompt"]
    assert actor.display_name in seen[0]["choice_trigger"]["prompt"]
    assert second not in actor.conditions and {first, magical, equal} <= set(actor.conditions)
    assert actor.reaction_available  # the choice never spends a Reaction


@pytest.mark.parametrize("kind", ["grappled", "restrained"])
@pytest.mark.parametrize("level", [19, 20, 21])
def test_liquid_body_only_prevents_lower_cl_ordinary_holds(kind, level):
    engine = _hold_fight(level)
    _cast(engine, DEEP)
    assert bool(_grip(engine, kind=kind)) == (level >= 20)
    assert _grip(engine, kind=kind, physical=False)  # magical condition with identical name is unaffected


@pytest.mark.parametrize("level", [20, 21])
@pytest.mark.parametrize("save", [None, "STR"])
def test_liquid_body_equal_or_higher_hold_escape_has_advantage(level, save):
    engine = _hold_fight(level)
    _grip(engine, save=save)
    _cast(engine, DEEP)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Escape grapple")
    engine.execute_intent(ActionIntent(intent_id="r11-escape", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids))
    rolls = [e.payload for e in engine.events if e.event_type == ("SAVE_ROLLED" if save else "CHECK_ROLLED")
             and e.source_definition_id == candidate.source_definition_id]
    assert rolls
    assert (rolls[-1] if save else rolls[-1]["actor"])["mode"] == "ADVANTAGE"


@pytest.mark.parametrize("save", [None, "STR"])
@pytest.mark.parametrize("chosen", ["physical", "magical"])
def test_liquid_body_mixed_escape_tests_only_the_chosen_hold(save, chosen):
    from combat.gate2_runtime_models import ReactionDecision

    engine = _hold_fight(20)
    magical = next(iter(_grip(engine, physical=False)))
    physical = next(iter(_grip(engine, save=save)))
    actor = engine.state.actors[ME]
    for key, dc in ((physical, 1), (magical, 500)):
        actor.conditions[key] = actor.conditions[key].model_copy(
            update={"data": {**actor.conditions[key].data, "escape_dc": dc}})
    _cast(engine, DEEP)
    selected = physical if chosen == "physical" else magical
    seen = []

    def answer(request):
        seen.append(request)
        assert set(request["legal_option_ids"]) == {physical, magical}
        assert "Deep’s Embrace" in request["choice_trigger"]["prompt"]
        assert "Escape grapple" in request["choice_trigger"]["prompt"]
        assert actor.display_name in request["choice_trigger"]["prompt"]
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=ME,
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(selected,)), None

    engine.set_reaction_provider(answer)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Escape grapple")
    engine.execute_intent(ActionIntent(intent_id="r11-mixed-escape", decision_id=candidate.decision_id,
                                      candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                      actor_id=ME, target_ids=candidate.target_ids))
    assert len(seen) == 1
    saving = save and chosen == "physical"
    rolls = [e.payload for e in engine.events if e.source_definition_id == candidate.source_definition_id
             and e.event_type == ("SAVE_ROLLED" if saving else "CHECK_ROLLED")]
    assert len(rolls) == 1
    roll = rolls[0] if saving else rolls[0]["actor"]
    assert roll["mode"] == ("ADVANTAGE" if chosen == "physical" else "NORMAL")
    assert rolls[0]["dc"] == (1 if chosen == "physical" else 500)
    assert magical in actor.conditions
    assert (physical not in actor.conditions) == (chosen == "physical")
    assert actor.reaction_available and not actor.action_available


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_liquid_body_mixed_escape_service_preview(tmp_path, mode):
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService, _ReactionRequired

    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="R11-MIXED-PREVIEW", typed_bundles=(compile_character(_sheet(DEEP), actor_id=ME),
                                                     compile_character(_sheet(MOON, cl=20), actor_id=AN)),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine = session.engine
    while engine.state.current_actor_id != ME:
        engine.end_turn()
    magical = next(iter(_grip(engine, physical=False)))
    physical = next(iter(_grip(engine)))
    _cast(engine, DEEP)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Escape grapple")
    intent = ActionIntent(intent_id="r11-mixed-preview", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=ME, target_ids=candidate.target_ids)
    metadata = {"participant_control_modes": {ME: mode, AN: "LOCAL_AUTO"}}
    before = engine.state.model_dump(mode="json")
    answers = ()
    if mode == "MANUAL":
        with pytest.raises(_ReactionRequired) as paused:
            service._run_preview(session, metadata, intent, ())
        context = paused.value.context
        assert set(context.legal_option_ids) == {physical, magical}
        assert "Deep’s Embrace" in context.choice_trigger["prompt"]
        assert "Escape grapple" in context.choice_trigger["prompt"]
        answers = (ReactionDecision(checkpoint=context.checkpoint, reactor_id=ME,
                                   reaction_source_id=context.reaction_source_id, selection="USE",
                                   option_ids=(physical,)),)
    preview = service._run_preview(session, metadata, intent, answers)
    assert preview["resolved_reactions"][0]["option_ids"] == [physical]
    rolls = [e["payload"] for e in preview["events"] if e["event_type"] == "CHECK_ROLLED"
             and e["source_definition_id"] == candidate.source_definition_id]
    assert rolls[-1]["actor"]["mode"] == "ADVANTAGE"
    assert not any(e["event_type"] == "CONDITION_REMOVED" and e["payload"].get("instance_id") == magical
                   for e in preview["events"])
    assert engine.state.model_dump(mode="json") == before


def test_liquid_body_prior_saved_bundle_keeps_aggregate_escape():
    engine = _hold_fight(20)
    for key, action in list(engine.action_catalog.items()):
        typed = action.parameters.get("typed") or {}
        if typed.get("source") == DEEP:
            effects = [{k: v for k, v in row.items() if k != "individual_escape"} for row in typed["effects"]]
            engine.action_catalog[key] = action.model_copy(update={"parameters": {**action.parameters, "typed": {**typed, "effects": effects}}})
    _grip(engine)
    _grip(engine, physical=False)
    _cast(engine, DEEP)
    def unexpected(request):
        pytest.fail("Prior saved bundle must not ask a new escape choice")
    engine.set_reaction_provider(unexpected)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Escape grapple")
    engine.execute_intent(ActionIntent(intent_id="r11-old-mixed", decision_id=candidate.decision_id,
                                      candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                      actor_id=ME, target_ids=candidate.target_ids))
    rolls = [e.payload for e in engine.events if e.event_type == "CHECK_ROLLED"]
    assert rolls[-1]["actor"]["mode"] == "NORMAL"


def test_liquid_body_old_saved_bundle_does_not_gain_hold_rules():
    engine = _hold_fight()
    for key, action in list(engine.action_catalog.items()):
        typed = action.parameters.get("typed") or {}
        if typed.get("source") == DEEP:
            effects = [{k: v for k, v in row.items() if k != "physical_holds"} for row in typed["effects"]]
            engine.action_catalog[key] = action.model_copy(update={"parameters": {**action.parameters, "typed": {**typed, "effects": effects}}})
    existing = _grip(engine)
    _cast(engine, DEEP)
    assert existing <= set(engine.state.actors[ME].conditions)
    assert _grip(engine)


def test_liquid_body_hold_protection_expires_and_ai_default_ends_one():
    engine = _hold_fight()
    existing = _grip(engine) | _grip(engine)
    _cast(engine, DEEP)
    assert len(existing & set(engine.state.actors[ME].conditions)) == 1
    assert not _grip(engine)
    engine.end_turn()
    engine.end_turn()
    assert _grip(engine)


def test_liquid_body_does_not_boost_escape_from_magical_or_mixed_holds():
    from combat import ext

    engine = _hold_fight(20)
    physical = _grip(engine)
    magical = _grip(engine, physical=False)
    _cast(engine, DEEP)
    actor = engine.state.actors[ME]
    for keys in (magical, physical | magical):
        assert "ADVANTAGE" not in ext.run("escape_mode", engine, actor, [actor.conditions[key] for key in keys])


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_liquid_body_service_preview_asks_player_and_automatically_answers_ai(tmp_path, mode):
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService, _ReactionRequired

    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="R11-HOLD-PREVIEW", typed_bundles=(compile_character(_sheet(DEEP), actor_id=ME),
                                                    compile_character(_sheet(MOON, cl=19), actor_id=AN)),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine = session.engine
    while engine.state.current_actor_id != ME:
        candidate = next(c for c in engine.legal_candidates() if c.display_name == "End turn")
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"r11-preview-turn-{candidate.state_version}", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=engine.state.current_actor_id, target_ids=candidate.target_ids))
    eligible = _grip(engine) | _grip(engine)
    candidate = next(c for c in engine.legal_candidates()
                     if (getattr(engine.action_catalog.get(c.source_definition_id), "parameters", {}).get("typed") or {}).get("source") == DEEP)
    intent = ActionIntent(intent_id="r11-service-preview", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=ME, target_ids=candidate.target_ids)
    metadata = {"participant_control_modes": {ME: mode, AN: "LOCAL_AUTO"}}
    before = engine.state.model_dump(mode="json")
    answers = ()
    if mode == "MANUAL":
        with pytest.raises(_ReactionRequired) as paused:
            service._run_preview(session, metadata, intent, ())
        context = paused.value.context
        assert set(context.legal_option_ids) == eligible
        assert "Deep’s Embrace" in context.choice_trigger["prompt"]
        answers = (ReactionDecision(checkpoint=context.checkpoint, reactor_id=ME,
                                   reaction_source_id=context.reaction_source_id, selection="USE",
                                   option_ids=(sorted(eligible)[-1],)),)
    preview = service._run_preview(session, metadata, intent, answers)
    assert len(preview["resolved_reactions"]) == 1
    assert preview["resolved_reactions"][0]["selection"] == "USE"
    assert len(preview["resolved_reactions"][0]["option_ids"]) == 1
    assert engine.state.model_dump(mode="json") == before


def test_liquid_body_activation_costs_qi_without_damage_grapple_or_mantle_ac():
    from combat.ext.abyssal_depths import LIQUID

    engine = _fight(DEEP)
    actor = engine.state.actors[ME]
    hp, qi = actor.current_hp, actor.resources["resource:core.qi"]
    _cast(engine, DEEP)
    assert actor.current_hp == hp
    assert actor.resources["resource:core.qi"] == qi - 3
    assert not actor.bonus_action_available
    assert any(c.condition_id == LIQUID for c in actor.conditions.values())
    assert not any(c.condition_id == "condition:typed.grappled" for c in actor.conditions.values())
    assert not any(m.target_field == "armor_class" for m in actor.modifiers.values())


@pytest.mark.parametrize("damage_type", ["BLUDGEONING", "PIERCING", "SLASHING", "FORCE"])
@pytest.mark.parametrize("attack_kind", ["weapon", "unarmed", "other", None])
def test_liquid_body_resists_only_weapon_bps_and_expires(damage_type, attack_kind):
    from combat import typed_reactions
    from combat.ext.abyssal_depths import LIQUID

    engine = _fight(DEEP)
    actor, foe = engine.state.actors[ME], engine.state.actors[AN]
    # An actual compiled caster receives the packet; vary its source catalog to
    # distinguish weapons, Unarmed Strikes, technique attacks and direct damage.
    original = next(iter(engine.action_catalog.values()))
    source = "action:r11.packet"
    effects = [{"type": "attack", "attack_kind": attack_kind}] if attack_kind else [{"type": "damage"}]
    engine.action_catalog[source] = original.model_copy(update={
        "source_definition_id": source, "parameters": {"typed": {"effects": effects}}})
    assert typed_reactions.defend(engine, actor, 11, damage_type, source, foe.entity_id) == 11
    _cast(engine, DEEP)
    expected = 5 if attack_kind == "weapon" and damage_type != "FORCE" else 11
    assert typed_reactions.defend(engine, actor, 11, damage_type, source, foe.entity_id) == expected
    engine.end_turn()
    assert any(c.condition_id == LIQUID for c in actor.conditions.values())
    engine.end_turn()
    assert engine.state.current_actor_id == ME
    assert not any(c.condition_id == LIQUID for c in actor.conditions.values())
    assert typed_reactions.defend(engine, actor, 11, damage_type, source, foe.entity_id) == 11


def test_liquid_body_survives_a_committed_fight_reload_and_replay(tmp_path):
    from combat.ext.abyssal_depths import LIQUID
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(
        match_seed="R11-LIQUID-SAVED", typed_bundles=(compile_character(_sheet(DEEP), actor_id=ME),
                                                     compile_character(_sheet(MOON, cl=19), actor_id=AN)),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})

    def take(candidate):
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"r11-saved-{candidate.state_version}", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=session.engine.state.current_actor_id, target_ids=candidate.target_ids,
            destination=candidate.destination))

    # Establish the hold through committed combat actions, so replay sees its source
    # event and no fixture-only changes create holes in the event journal.
    for _ in range(20):
        actor = session.engine.state.actors[ME]
        held = {key for key, c in actor.conditions.items() if c.condition_id == "condition:typed.grappled"}
        if session.engine.state.current_actor_id == ME and held:
            break
        candidates = session.engine.legal_candidates()
        grapple = next((c for c in candidates if c.actor_id == AN and ME in c.target_ids
                        and (getattr(session.engine.action_catalog.get(c.source_definition_id), "parameters", {}).get("typed") or {}).get("unarmed_option") == "grapple"), None)
        take(grapple or next(c for c in candidates if c.display_name == "End turn"))
    assert held and session.engine.state.current_actor_id == ME
    action_ids = {key for key, action in session.engine.action_catalog.items()
                  if (action.parameters.get("typed") or {}).get("source") == DEEP}
    take(next(c for c in session.engine.legal_candidates() if c.source_definition_id in action_ids))
    reloaded = persistence.load_match(session.match_id)
    before = session.engine.state.actors[ME]
    after = reloaded.engine.state.actors[ME]
    assert any(c.condition_id == LIQUID for c in after.conditions.values())
    assert next(c.data["hold_cl"] for c in after.conditions.values() if c.condition_id == LIQUID) == 20
    assert next(c.data["individual_escape"] for c in after.conditions.values() if c.condition_id == LIQUID) == 1
    assert not held & set(after.conditions)
    assert after.conditions == before.conditions
    assert after.resources == before.resources
    assert reloaded.verify()["status"] == "PASS"
