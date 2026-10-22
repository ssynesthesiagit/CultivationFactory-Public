"""Gu Xiangze's automation (owner 2026-09-28, "automate every aspect"): Berserker's Batter (missing from the
character sheet's automatic-sphere-component list; supplied by combat/ext/gu_berserker.py) and its Exertion
talents, Shatter Earth's area-option fix, and Wrestling's Applying a Slam / Choke Hold / Grandstanding Slam
(supplied by combat/ext/gu_wrestling.py). See both plug-in modules' module docstrings for what the printed
rules say and why each shortcut was taken."""
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.gu"


def _bundle(talents, spheres, granted=()):
    """`granted`: sphere-base ids the real sheet's own automatic_sphere_component_record_ids would carry (e.g.
    BRUTE_BASE_BRUTAL_SHOVE) -- this minimal fixture sheet has none of its own, unlike Gu's real one."""
    return compile_character({**SHEET, "equipment": [], "spheres_and_talents": {
        "sphere_record_ids": spheres, "learned_talent_record_ids": talents, "automatic_sphere_component_record_ids": list(granted)}},
                             actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="GU", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _three_actor_engine(bundle, foe_at=(4, 6), blocker_at=(5, 6)):
    """ME, AN (the shove target) and a third body at blocker_at, one square past AN, for Impact Collision."""
    third = LEE
    engine = Gate4ControllerEngine(ROOT, match_seed="GU3", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN, third],
                                                 "team_by_actor": {ME: "team:a", AN: "team:b", third: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]},
                                                                        third: {"x": blocker_at[0], "y": blocker_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine, third


def _use(engine, name, target_id=None):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME,
                                       target_ids=target_id and [target_id] or candidate.target_ids))
    return candidate


# ---------------------------------------------------------------- Batter (Berserker)

def test_batter_is_granted_by_the_sphere_alone_and_deals_unarmed_damage():
    bundle = _bundle([], ["tianxia.sphere.berserker"])
    batter = next(row for row in bundle["action_catalog"] if row["display_name"] == "Batter")
    assert batter["economy"] == "ACTION"
    typed = batter["parameters"]["typed"]
    assert typed["effects"][0]["attack_kind"] == "unarmed"
    # Battered rides the shared ``batter`` effect (rider lane C13: "On a hit that deals damage, the target becomes Battered until the
    # end of your next turn" -- the Batterer's next turn, on a damaging hit, as the weapon Batters already did).
    assert any(hit.get("type") == "batter" for hit in typed["effects"][0]["on_hit"])


def test_unarmed_batter_with_null_weapon_damage_resolves_without_crashing():
    bundle = _bundle([], ["tianxia.sphere.berserker"])
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    weapon = next(row for row in bundle["action_catalog"] if row["display_name"] == "Batter")["parameters"]["typed"].get("weapon") or {}
    assert weapon.get("damage") is None
    for attempt in range(20):
        candidate = next((c for c in engine.legal_candidates() if c.display_name == "Batter"), None)
        assert candidate is not None
        before = foe.current_hp
        engine.execute_intent(ActionIntent(intent_id=f"null-damage-batter-{attempt}", decision_id=candidate.decision_id,
                                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                           actor_id=ME, target_ids=candidate.target_ids))
        if foe.current_hp < before:
            return
        me.action_available = True
        engine.state.current_actor_id = ME
    raise AssertionError("unarmed Batter did not land a damaging hit in 20 attempts")


def test_batter_applies_battered_and_bone_breaker_on_a_hit_brutal_strike_is_a_separate_choice():
    """Body 2026-09-29 (docket-peer-reported bug fix): the printed rule is "apply one Exertion talent" per Batter, not
    every owned one stacked for free. Plain Batter carries none of them; Brutal Strike is its own optional
    "Batter + Brutal Strike" choice (combat/ext/docket_maneuvers.py's generic system); Bone-Breaker (needing custom
    code) is a free toggle (combat/ext/gu_berserker.py) that defaults to the only Exertion talent owned here."""
    bundle = _bundle(["TAL_BERSERKER_BONE_BREAKER", "TAL_BERSERKER_BRUTAL_STRIKE"], ["tianxia.sphere.berserker"])
    batter = next(row for row in bundle["action_catalog"] if row["display_name"] == "Batter")
    typed = batter["parameters"]["typed"]
    assert typed["numbers"]["attack_bonus"] == typed["numbers"]["pb"] + 2  # no Brutal Strike baked into the plain Batter
    assert not any(hit.get("type") == "extra_damage" and hit.get("flat") == 10 for hit in typed["effects"][0]["on_hit"])
    brutal = next(row for row in bundle["action_catalog"] if row["display_name"] == "Batter + Brutal Strike")
    brutal_typed = brutal["parameters"]["typed"]
    # docket_maneuvers.py's generic modifier-variant system folds a self-targeted attack roll modifier into the
    # attack effect's own first_roll_bonus (typed_executor.py reads it for the first roll only), not numbers.attack_bonus.
    assert brutal_typed["effects"][0].get("first_roll_bonus") == -5  # Brutal Strike's flat -5
    assert any(hit.get("type") == "extra_damage" and hit.get("flat") == 10 for hit in brutal_typed["effects"][0]["on_hit"])
    assert {row["display_name"] for row in bundle["action_catalog"]} >= {"Exertion: Bone-Breaker", "Exertion: off"}
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    hit = False
    for attempt in range(20):
        candidate = next((c for c in engine.legal_candidates() if c.display_name == "Batter"), None)
        if candidate is None:
            me.action_available = True
            engine.state.current_actor_id = ME
            continue
        before = foe.current_hp
        engine.execute_intent(ActionIntent(intent_id=f"b{attempt}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                           state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))
        if foe.current_hp < before:
            hit = True
            break
        me.action_available = True
        engine.state.current_actor_id = ME
    assert hit
    assert any(c.condition_id == "condition:typed.battered" for c in foe.conditions.values())
    assert any(m.target_field == "attack_roll" and m.operation == "SUBTRACT_DIE" for m in foe.modifiers.values())  # Bone-Breaker, the default choice


def test_batter_exertion_toggle_picks_one_talent_and_brutal_strike_variant_does_not_double_apply():
    """Bell-Ringer and Bone-Breaker share one free Exertion toggle: choosing Bell-Ringer stops Bone-Breaker from also
    firing, and using the separate "Batter + Brutal Strike" action does not also trigger the toggle's choice (the
    printed rule is ONE Exertion talent, however it was picked)."""
    from combat.ext.gu_berserker import EXERTION_CHOICE

    bundle = _bundle(["TAL_BERSERKER_BONE_BREAKER", "TAL_BERSERKER_BELL_RINGER", "TAL_BERSERKER_BRUTAL_STRIKE"], ["tianxia.sphere.berserker"])
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    bell_ringer = next(c for c in engine.legal_candidates() if c.display_name == "Exertion: Bell-Ringer")
    engine.execute_intent(ActionIntent(intent_id="choose", decision_id=bell_ringer.decision_id, candidate_id=bell_ringer.candidate_id,
                                       state_version=bell_ringer.state_version, actor_id=ME, target_ids=bell_ringer.target_ids))
    me.action_available = True
    engine.state.current_actor_id = ME
    assert any(c.condition_id == EXERTION_CHOICE and (c.data or {}).get("choice") == "bell_ringer" for c in me.conditions.values())
    hit = False
    for attempt in range(20):
        candidate = next((c for c in engine.legal_candidates() if c.display_name == "Batter + Brutal Strike"), None)
        if candidate is None:
            me.action_available = True
            engine.state.current_actor_id = ME
            continue
        before = foe.current_hp
        engine.execute_intent(ActionIntent(intent_id=f"bs{attempt}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                           state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))
        if foe.current_hp < before:
            hit = True
            break
        me.action_available = True
        engine.state.current_actor_id = ME
    assert hit
    assert not any(m.target_field == "attack_roll" and m.operation == "SUBTRACT_DIE" for m in foe.modifiers.values())  # not Bone-Breaker
    assert not any(c.condition_id == "condition:typed.bell_rung" for c in foe.conditions.values())  # nor Bell-Ringer: Brutal Strike was chosen instead


# ---------------------------------------------------------------- Shatter Earth (Berserker)

def test_shatter_earth_has_three_area_options_and_costs_martial_focus():
    bundle = _bundle(["TAL_BERSERKER_SHATTER_EARTH"], ["tianxia.sphere.berserker"])
    rows = [row for row in bundle["action_catalog"] if row["display_name"].startswith("Shatter Earth")]
    labels = {row["display_name"] for row in rows}
    assert labels == {"Shatter Earth: Spaces within 5 feet", "Shatter Earth: 10-foot cone", "Shatter Earth: 15-foot line"}
    for row in rows:
        assert row["costs"] == [["resource:core.martial_focus", 1]]
        effect = row["parameters"]["typed"]["effects"][0]
        assert effect["type"] == "save" and effect["ability"] == "STR_OR_DEX"


# ---------------------------------------------------------------- Applying a Slam (Wrestling)

def test_apply_a_slam_requires_the_target_be_grappled_by_the_actor():
    bundle = _bundle(["TAL_WRESTLING_CHOKE_HOLD"], ["tianxia.sphere.wrestling"])
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert "Apply a Slam: Choke Hold" in names
    assert "Apply a Slam: Cultivation-Suppressing Grip" not in names  # not owned
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert not [c for c in engine.legal_candidates() if c.display_name == "Apply a Slam: Choke Hold"]  # not grappled yet
    engine._apply_condition(foe, "condition:typed.grappled", "test:grapple", ME, expires_on=None)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Apply a Slam: Choke Hold")
    engine.execute_intent(ActionIntent(intent_id="slam1", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=[AN]))
    assert any(c.condition_id == "condition:typed.choke_hold" and c.source_actor_id == ME for c in foe.conditions.values())


# ---------------------------------------------------------------- Hammer / Break Defenses / Focused Might (Brute)

def test_hammer_only_deals_damage_on_an_actual_collision_while_holding_focus():
    bundle = _bundle(["TAL_BRUTE_HAMMER"], ["tianxia.sphere.brute"], granted=["BRUTE_BASE_BRUTAL_SHOVE"])
    engine, blocker_id = _three_actor_engine(bundle, foe_at=(4, 6), blocker_at=(5, 6))
    me, foe, blocker = engine.state.actors[ME], engine.state.actors[AN], engine.state.actors[blocker_id]
    assert me.resources.get(FOCUS_ID, 0) >= 1  # Brute starts holding Martial Focus
    foe_hp, blocker_hp = foe.current_hp, blocker.current_hp
    hit = False
    for attempt in range(20):
        candidate = next((c for c in engine.legal_candidates() if c.display_name == "Brutal Shove"), None)
        if candidate is None:
            me.action_available = True
            engine.state.current_actor_id = ME
            continue
        engine.execute_intent(ActionIntent(intent_id=f"h{attempt}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                           state_version=candidate.state_version, actor_id=ME, target_ids=[AN]))
        if foe.position.x != 4 or foe.position.y != 6 or foe.current_hp < foe_hp:
            hit = True
            break
        me.action_available = True
        engine.state.current_actor_id = ME
    assert hit
    # Blocked at the very first step (blocker sits one square past the target): both take the same collision damage.
    assert blocker.current_hp < blocker_hp
    assert (foe_hp - foe.current_hp) >= (blocker_hp - blocker.current_hp) > 0


FOCUS_ID = "resource:core.martial_focus"


def test_break_defenses_and_focused_might_after_a_successful_shove():
    bundle = _bundle(["TAL_BRUTE_BREAK_DEFENSES", "TAL_BRUTE_FOCUSED_MIGHT"], ["tianxia.sphere.brute"], granted=["BRUTE_BASE_BRUTAL_SHOVE"])
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert "Focused Might: Regain Martial Focus" in names
    engine = _engine(bundle)  # AN adjacent, within Brutal Shove's 5-foot reach
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    # Regain Martial Focus requires that Focus has actually been spent.
    me.resources['resource:core.martial_focus'] = 0
    assert not [c for c in engine.legal_candidates() if c.display_name == "Focused Might: Regain Martial Focus"]
    shoved = False
    for attempt in range(20):
        candidate = next((c for c in engine.legal_candidates() if c.display_name == "Brutal Shove"), None)
        if candidate is None:
            me.action_available = True
            engine.state.current_actor_id = ME
            continue
        engine.execute_intent(ActionIntent(intent_id=f"bd{attempt}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                           state_version=candidate.state_version, actor_id=ME, target_ids=[AN]))
        if any(m.target_field == "incoming_attack_mode" for m in foe.modifiers.values()):
            shoved = True
            break
        me.action_available = True
        engine.state.current_actor_id = ME
    assert shoved  # Break Defenses: the next attack against the shoved creature has Advantage
    me.bonus_action_available = True
    ready = [c for c in engine.legal_candidates() if c.display_name == "Focused Might: Regain Martial Focus"]
    assert ready and ME in ready[0].target_ids


def test_grandstanding_slam_frightens_onlookers_when_a_slam_is_applied():
    bundle = _bundle(["TAL_WRESTLING_CHOKE_HOLD", "TAL_WRESTLING_GRANDSTANDING_SLAM"], ["tianxia.sphere.wrestling"])
    slam_action = next(row for row in bundle["action_catalog"] if row["display_name"] == "Apply a Slam: Choke Hold")
    assert slam_action["costs"] == [["resource:core.martial_focus", 1]]  # Grandstanding Slam expends Martial Focus
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._apply_condition(foe, "condition:typed.grappled", "test:grapple", ME, expires_on=None)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Apply a Slam: Choke Hold")
    engine.execute_intent(ActionIntent(intent_id="slam2", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=[AN]))
    assert any(c.condition_id == "condition:typed.choke_hold" for c in foe.conditions.values())


# ---------------------------------------------------------------- Sand Step / Abrading Ward (Sand)

def _lay_sand_at(engine, owner_id, position):
    """The shape combat/ext/gu_sand.py._in_own_sand looks for: a typed zone owned by owner_id, tagged sand,
    covering position -- built the same way Gather Sand's own zone_spec would, without needing a full cast."""
    from combat.zones import KIND
    from combat.gate2_runtime_models import Position, ZoneState

    zone_id = f"zone:test-sand-{owner_id}"
    engine.state.zones[zone_id] = ZoneState(
        zone_id=zone_id, source_definition_id="action:test.sand", owner_id=owner_id, active=True,
        center=Position(x=position[0], y=position[1]), radius_cells=0,
        affected_cells=(Position(x=position[0], y=position[1]),), concentration_link=False, created_round=1,
        trigger_profile={"kind": KIND, "name": "Sand Terrain", "terrain": ["sand terrain"], "visual": {"material": "sand"}})


def test_sand_step_disadvantages_an_opportunity_attack_from_its_own_sand():
    from combat.ext import gu_sand

    bundle = _bundle(["TAL_SAND_SAND_STEP"], ["tianxia.sphere.sand"])
    fight = _engine(bundle)
    me = fight.state.actors[ME]
    _lay_sand_at(fight, ME, (me.position.x, me.position.y))

    class _Ctx:
        typed = {"opportunity_of": "action:some.weapon"}
        engine = fight

    assert gu_sand.sand_step(_Ctx(), me) == "DISADVANTAGE"
    _Ctx.typed = {}  # a normal attack (not an opportunity attack) is untouched
    assert gu_sand.sand_step(_Ctx(), me) is None


def test_abrading_ward_damages_a_hostile_creature_that_starts_its_turn_in_the_sand():
    bundle = _bundle(["TAL_SAND_ABRADING_WARD"], ["tianxia.sphere.sand"])
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _lay_sand_at(engine, ME, (foe.position.x, foe.position.y))
    before = foe.current_hp
    from combat.ext import gu_sand
    gu_sand.abrading_ward(engine, foe)
    assert foe.current_hp == before - me.proficiency_bonus


# ---------------------------------------------------------------- Digestive Mantle base Temp HP (Hunger)

def test_digestive_mantle_grants_its_base_temp_hp_on_every_variant():
    bundle = _bundle([], ["tianxia.sphere.hunger"], granted=["HUNGER_BASE_DIGESTIVE_MANTLE"])
    variants = [row for row in bundle["action_catalog"] if row["display_name"].startswith("Digestive Mantle:")]
    assert variants
    for row in variants:
        first = row["parameters"]["typed"]["effects"][0]
        assert first["type"] == "temp_hp" and first["formula"] == "double_pb"  # twice Proficiency Bonus + key ability modifier
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    me.resources["resource:named.satiety"] = me.resource_maximums.get("resource:named.satiety", 1)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Digestive Mantle: Beast Strength")
    engine.execute_intent(ActionIntent(intent_id="mantle", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=[ME]))
    assert me.temporary_hp == 2 * me.proficiency_bonus + 2  # +2: the SHEET fixture's flat +2 ability modifiers
