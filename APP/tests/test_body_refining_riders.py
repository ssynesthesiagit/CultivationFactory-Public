"""Body Refining printed combat riders: data-driven, owned and inert without the variant.

These regressions cover the review findings that the variants deferred their
printed combat clauses and ignored the printed key-ability alternatives. They
read the shipped authority and synthetic sheets only; no private fixtures.
"""
from types import SimpleNamespace
import json

import pytest

from combat.factory_compiler import compile_character
from combat.ext import br_variants as bv
from combat.ext import free_uses
from tests.body_refining_support import sheet

ACTOR = "actor:factory.body_student"
FOCUS = "resource:core.martial_focus"


class Actor(SimpleNamespace):
    pass


def make_actor(**overrides):
    base = dict(entity_id=ACTOR, display_name="Body Student", team_id="team:a", conditions={}, resources={},
                resource_maximums={}, turn_flags={}, active=True, current_hp=20, maximum_hp=40,
                movement_remaining_ft=0, position=SimpleNamespace(x=0, y=0))
    base.update(overrides)
    return Actor(**base)


def make_engine(rows, actor, *, round_number=1, slot=0):
    engine = Actor()
    engine.typed_passive_rows = {actor.entity_id: list(rows)}
    engine.state = SimpleNamespace(round_number=round_number, current_slot_index=slot, zones={},
                                   actors={actor.entity_id: actor}, current_actor_id=actor.entity_id,
                                   event_sequence=0, objects={})
    engine.actions = []
    engine.action_catalog = {}
    engine.events = []
    engine._gain_resource = lambda target, resource, amount, source: (
        target.resources.__setitem__(resource, int(target.resources.get(resource) or 0) + int(amount)),
        engine.events.append(("GAIN", resource, int(amount))))
    engine._append_event = lambda event_type, *args, **kwargs: engine.events.append((event_type, args, kwargs))
    engine._grant_temp_hp = lambda target, amount, source, owner: (
        engine.events.append(("TEMP_HP", int(amount))),
        setattr(target, "temporary_hp", int(getattr(target, "temporary_hp", 0) or 0) + int(amount)))
    def apply_condition(target, condition_id, source, owner, *, expires_on=None, data=None):
        instance = SimpleNamespace(condition_id=condition_id, data=dict(data or {}), source_definition_id=source,
                                   source_actor_id=owner, expires_on=expires_on)
        instance.instance_id = condition_id
        target.conditions[condition_id] = instance
    engine._apply_condition = apply_condition
    def remove_condition_instance(target, instance_id, source, **kwargs):
        target.conditions.pop(instance_id, None)
        return True
    engine._remove_condition_instance = remove_condition_instance
    engine._distance_actor_to_actor = lambda left, right: 5
    engine._roll_save = lambda target, ability, dc, source, *args, **kwargs: SimpleNamespace(total=dc - 1)
    engine._add_modifier = lambda target, source, field, operation, value, applies_to, **kw: (
        engine.events.append(("MODIFIER", field, value)))
    return engine


def variants(document, actor_id=ACTOR):
    bundle = compile_character(document, actor_id=actor_id)
    return [row for row in bundle["typed_passives"] if row.get("block") == bv.BLOCK], bundle


def sphere(sid, *, talents=(), **scores):
    document = sheet(spheres=[sid], talents=list(talents))
    document["ability_scores_and_statistics"]["abilities"] = [
        {"ability": ability, "score": scores.get(ability, 12), "modifier": (scores.get(ability, 12) - 10) // 2}
        for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")]
    return document


# --------------------------------------------------------------------- the named review example
def test_air_gather_current_is_free_during_the_attack_or_dash_action_once_per_turn():
    """Air: "when you take the Attack action or Dash action, you may use Gather
    Current as part of the same action once per turn." The free sibling is
    compiled with no economy, offered only after Attack/Dash, and spent once."""
    rows, bundle = variants(sphere("tianxia.sphere.air", talents=["AIR_BASE_GATHER_CURRENT"]))
    free = [action for action in bundle["action_catalog"] if "Gather Current" in action["display_name"]
            and action["display_name"].endswith("(free)")]
    assert free and all(action["economy"] == "NONE" for action in free)
    grant = free[0]["parameters"]["free_use"]
    assert grant["of"] == ["Gather Current"] and grant["always"] is True
    assert grant["requires"] == bv.ATTACK_OR_DASH and grant["once"] == "turn"

    actor = make_actor()
    engine = make_engine(rows, actor)
    engine.action_catalog = {"action:core.attack": SimpleNamespace(display_name="Attack")}
    assert bv.free_use_available(engine, actor, grant) is False  # nothing taken yet
    # The real completion route: an ordinary Attack action resolving reaches typed_reactions.on_action_completed,
    # which runs the general action_completed hook (review BRS1F7R finding 1). No technique_used is involved.
    from combat import typed_reactions
    typed_reactions.on_action_completed(engine, actor, "ACTION", "action:core.attack")
    assert bv.free_use_available(engine, actor, grant) is True
    bv.mark_free_use_spent(engine, actor, grant)
    assert bv.free_use_available(engine, actor, grant) is False  # once per turn


def test_lightning_gather_charge_uses_the_same_general_free_use_seam():
    rows, bundle = variants(sphere("tianxia.sphere.lightning", talents=["TAL_LIGHTNING_GATHER_CHARGE"]))
    free = [a for a in bundle["action_catalog"] if a["display_name"].startswith("Gather Charge") and a["display_name"].endswith("(free)")]
    assert free and free[0]["parameters"]["free_use"]["requires"] == bv.ATTACK_OR_DASH


# --------------------------------------------------------------------- payment
def test_owned_variant_pays_cp_with_stamina_from_the_authority_data():
    rows, _ = variants(sphere("tianxia.sphere.axes", talents=["TAL_AXES_HEWING_STRIKE"]))
    assert rows and rows[0]["payment"]["with"] == bv.STAMINA
    actor = make_actor(resources={bv.STAMINA: 10}, resource_maximums={bv.STAMINA: 10})
    engine = make_engine(rows, actor)
    engine.action_catalog["source"] = SimpleNamespace(
        owner_id=ACTOR, parameters={"typed": {"sphere": "tianxia.sphere.axes"}})
    plan = bv.variant_payment(engine, actor, "source", {"tianxia.path.body_refining": 2},
                              {"tianxia.path.body_refining": 2})
    assert plan is not None
    assert dict(plan.covered) == {"tianxia.path.body_refining": 2}
    assert dict(plan.costs) == {bv.STAMINA: 2}


def test_a_sphere_without_the_variant_payment_gets_no_substitution():
    rows, _ = variants(sphere("tianxia.sphere.air", talents=["AIR_BASE_GATHER_CURRENT"]))
    actor = make_actor(resources={bv.STAMINA: 10})
    engine = make_engine(rows, actor)
    engine.action_catalog["source"] = SimpleNamespace(
        owner_id=ACTOR, parameters={"typed": {"sphere": "tianxia.sphere.air"}})
    assert bv.variant_payment(engine, actor, "source", {"tianxia.path.body_refining": 2},
                              {"tianxia.path.body_refining": 2}) is None


# --------------------------------------------------------------------- unconditional riders
def test_printed_unconditional_riders_apply_only_to_the_owner():
    rows, _ = variants(sphere("tianxia.sphere.disease"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    assert bv.rider_resistance(engine, actor, "POISON", {}, None) == [
        {"kind": "resistance", "damage_types": ["POISON"]}]
    ctx = SimpleNamespace(engine=engine)
    assert bv.rider_saves(ctx, actor, "CON", {"disease"})["modes"] == ["ADVANTAGE"]

    dark_rows, _ = variants(sphere("tianxia.sphere.dark"))
    dark_engine = make_engine(dark_rows, actor)
    assert bv.rider_saves(SimpleNamespace(engine=dark_engine), actor, "WIS", {"frightened"})["modes"] == ["ADVANTAGE"]
    # A character without any variant row gets nothing, byte for byte.
    other = make_actor(entity_id="actor:factory.other")
    assert bv.rider_resistance(dark_engine, other, "POISON", {}, None) is None
    assert bv.rider_ac(dark_engine, other) is None


def test_conditional_ac_rider_requires_its_printed_state():
    rows, _ = variants(sphere("tianxia.sphere.magma"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    assert bv.rider_ac(engine, actor) is None
    actor.conditions["condition:typed.state.magma_armor"] = SimpleNamespace(
        condition_id="condition:typed.state.magma_armor", data={"name": "Magma Armor"})
    assert bv.rider_ac(engine, actor) == 1


def test_night_bound_body_gains_its_riders_in_dim_light_or_its_own_darkness():
    """Dark: "While standing inside Dim Light or your Darkness: Gain +1 AC. Gain
    Advantage on Dexterity (Stealth) checks." Dim Light is a light-shedding area
    on the table (a candle, a lantern), so the printed condition is evaluated
    rather than skipped: Bright Light, or no light at all, grants nothing."""
    from combat import typed_executor, zones
    from combat.gate2_runtime_models import Position, ZoneState
    from tests.test_auto_support import ME, _engine

    bundle = compile_character(sheet(spheres=["tianxia.sphere.dark"]), actor_id=ME)
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    foe = next(actor for actor in engine.state.actors.values() if actor is not me)

    def stealth_mode():
        return typed_executor.check_mode(me, "DEX", "Stealth", engine=engine, against_creature=foe)

    def area(zone_id, profile, owner):
        cells = tuple(Position(x=cell[0], y=cell[1])
                      for cell in engine.grid.footprint_cells(me.position, engine._footprint(me.entity_id)))
        engine.state.zones[zone_id] = ZoneState(
            zone_id=zone_id, source_definition_id="test:" + zone_id, owner_id=owner.entity_id, center=me.position,
            radius_cells=0, affected_cells=cells, concentration_link=False, duration_rounds=None,
            created_round=engine.state.round_number,
            trigger_profile={"kind": zones.KIND, "difficult": None, "triggers": [], "inside": [], "numbers": {},
                             **profile})
        zones.sync_inside(engine, "test:" + zone_id)
        return engine.state.zones[zone_id]

    assert engine._ac_modifier(me) == 0 and stealth_mode() == "NORMAL"

    candle = area("zone:test.dim", {"name": "Candlelight",
                                    "visual": {"material": "wax", "light": {"radius_ft": 10, "level": "dim"}}}, foe)
    assert engine._ac_modifier(me) == 1
    assert stealth_mode() == "ADVANTAGE"

    zones.remove(engine, candle, "test")
    area("zone:test.bright", {"name": "Sunlight",
                              "visual": {"material": "radiance", "light": {"radius_ft": 20, "level": "bright"}}}, foe)
    assert engine._ac_modifier(me) == 0 and stealth_mode() == "NORMAL"  # Bright Light is not Dim Light
    zones.remove(engine, engine.state.zones["zone:test.bright"], "test")

    # The printed "or your Darkness": the creature's own Darkness still counts.
    area("zone:test.dark", {"name": "Night's Darkness", "visual": {"material": "darkness", "darkness": True}}, me)
    assert engine._ac_modifier(me) == 1 and stealth_mode() == "ADVANTAGE"


def test_forced_movement_reduction_reads_martial_focus():
    rows, _ = variants(sphere("tianxia.sphere.brute"))
    actor = make_actor(resources={FOCUS: 0})
    engine = make_engine(rows, actor)
    ctx = SimpleNamespace(engine=engine)
    assert bv.rider_forced_movement(ctx, actor) == 0
    actor.resources[FOCUS] = 1
    assert bv.rider_forced_movement(ctx, actor) == 5


# --------------------------------------------------------------------- guard-zero rewards
def test_stamina_guard_zero_reward_is_once_per_round_and_owner_only():
    rows, _ = variants(sphere("tianxia.sphere.blood"))
    actor = make_actor(current_hp=10, maximum_hp=40)
    engine = make_engine(rows, actor)
    kwargs = {"actor_id": ACTOR, "payload": {"pending_after": 0, "spend": 1}}
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", kwargs)
    assert actor.current_hp == 12  # PB 2
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", kwargs)
    assert actor.current_hp == 12
    engine.state.round_number = 2
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", kwargs)
    assert actor.current_hp == 14
    # A packet reduced to anything other than 0 never pays.
    engine.state.round_number = 3
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", {"actor_id": ACTOR, "payload": {"pending_after": 3, "spend": 1}})
    assert actor.current_hp == 14
    # An actor with no variant rows receives nothing.
    other = make_actor(entity_id="actor:factory.other", current_hp=10)
    engine.state.actors[other.entity_id] = other
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", {"actor_id": other.entity_id, "payload": {"pending_after": 0, "spend": 1}})
    assert other.current_hp == 10


def test_start_of_turn_temporary_hp_is_granted_once_until_a_short_rest():
    rows, _ = variants(sphere("tianxia.sphere.flowers"))
    actor = make_actor(current_hp=10, maximum_hp=40)
    engine = make_engine(rows, actor)
    bv.rider_turn_start(engine, actor)
    assert ("TEMP_HP", 2) in engine.events
    marker = next(c for c in actor.conditions.values() if c.condition_id == "condition:typed.br_variant_temp")
    assert marker.expires_on == "UNTIL_SHORT_REST", "the printed limit is a short rest, never the fight"
    before = list(engine.events)
    bv.rider_turn_start(engine, actor)
    assert engine.events == before
    # Above half maximum HP the printed condition is not met.
    healed = make_actor(current_hp=30, maximum_hp=40)
    healed_engine = make_engine(rows, healed)
    bv.rider_turn_start(healed_engine, healed)
    assert not any(event[0] == "TEMP_HP" for event in healed_engine.events)


def test_blooming_body_temporary_hp_returns_after_the_engines_short_rest():
    """Regression across a short rest (addendum 3): the engine's own rest seam ends the marker."""
    from combat.factory_compiler import compile_character
    from tests.test_auto_support import ME, _engine

    bundle = compile_character(sheet(spheres=["tianxia.sphere.flowers"]), actor_id=ME)
    engine = _engine(bundle)
    actor = engine.state.actors[ME]
    actor.current_hp = max(1, int(actor.maximum_hp) // 4)  # printed "while below half maximum HP"
    bv.rider_turn_start(engine, actor)
    grants = engine.state.event_sequence
    bv.rider_turn_start(engine, actor)
    assert engine.state.event_sequence == grants, "a second start of turn does not regrant before the rest"
    engine.short_rest(actor.entity_id)
    assert not any(c.condition_id == "condition:typed.br_variant_temp" for c in actor.conditions.values())
    bv.rider_turn_start(engine, actor)
    assert engine.state.event_sequence > grants, "the short rest restored the once-per-rest Temporary HP"


# --------------------------------------------------------------------- persistence
def test_riders_and_payment_are_plain_json_in_the_compiled_bundle():
    rows, bundle = variants(sphere("tianxia.sphere.air", talents=["AIR_BASE_GATHER_CURRENT"]))
    reloaded = json.loads(json.dumps(bundle["typed_passives"]))
    restored = [row for row in reloaded if row.get("block") == bv.BLOCK]
    assert restored == rows
    assert all(isinstance(rider.get("clause"), int) for row in restored for rider in row["riders"])


# --------------------------------------------------------------------- Bone-Axe Body: Hewing Strike follow-up (clause 5)
BONE_AXE = "tianxia.brvariant.axes.bone-axe-body"
TARGET = "creature:bitten.target"
HEWING = "TAL_AXES_HEWING_STRIKE"


def _bone_axe_row(feet=10):
    return {"feature_id": BONE_AXE, "block": bv.BLOCK, "kind": "tianxia.sphere.axes", "numbers": {"pb": 3, "cl": 1},
            "riders": [{"kind": "hewing_athletics", "feet": feet, "mark": "Bite", "skill": "Athletics", "clause": "5"}]}


def _hewing_world(monkeypatch, *, moved=12, bitten=True):
    from combat import typed_executor
    from combat.ext import beauty_motion

    actor = make_actor()
    target = make_actor(entity_id=TARGET)
    engine = make_engine([_bone_axe_row()], actor)
    engine.state.actors[TARGET] = target
    context = {"kind": "check", "skill": "Athletics", "ability": "STR", "target_id": TARGET}
    engine.d20_context = lambda roll=None: dict(context)
    monkeypatch.setattr(beauty_motion, "moved_this_turn", lambda engine, actor: moved)
    monkeypatch.setattr(typed_executor, "bears_mark",
                        lambda subject, owner, mark=None: bitten and subject is target and mark == "Bite")
    return engine, actor, context


def _technique(engine, actor, source=HEWING):
    return SimpleNamespace(engine=engine, actor=actor, typed={"source": source})


def test_bone_axe_clause_five_is_automated_not_a_table_note():
    from pathlib import Path
    riders = json.loads((Path(__file__).resolve().parents[1] / "authority" / "body_refining" / "variant_riders.json").read_text())
    clause = riders["variants"][BONE_AXE]["5"]
    assert clause["automation"] == "compiled"
    assert clause["riders"][0]["kind"] == "hewing_athletics"


def test_bone_axe_follow_up_is_armed_only_by_hewing_strike_after_ten_feet(monkeypatch):
    engine, actor, _ = _hewing_world(monkeypatch, moved=9)
    bv.arm_hewing_follow_up(_technique(engine, actor))
    assert bv.HEWING_FLAG not in actor.turn_flags
    engine, actor, _ = _hewing_world(monkeypatch, moved=10)
    bv.arm_hewing_follow_up(_technique(engine, actor, source="TAL_AXES_SPLIT_THE_CHAIN"))
    assert bv.HEWING_FLAG not in actor.turn_flags
    bv.arm_hewing_follow_up(_technique(engine, actor))
    assert actor.turn_flags[bv.HEWING_FLAG] == bv._turn_key(engine, actor)


def test_bone_axe_adds_proficiency_once_to_athletics_against_a_bitten_target(monkeypatch):
    engine, actor, _ = _hewing_world(monkeypatch)
    actor.turn_flags[bv.HEWING_FLAG] = bv._turn_key(engine, actor)
    roll = SimpleNamespace(actor_id=ACTOR)
    assert bv.hewing_athletics_bonus(engine, roll, None) == {"source_id": BONE_AXE, "bonus": 3}
    # Spent by that check: a second Athletics check this turn gets nothing.
    assert bv.hewing_athletics_bonus(engine, roll, None) is None


def test_bone_axe_bonus_needs_athletics_and_a_bitten_target(monkeypatch):
    engine, actor, context = _hewing_world(monkeypatch)
    actor.turn_flags[bv.HEWING_FLAG] = bv._turn_key(engine, actor)
    context["skill"] = "Acrobatics"
    assert bv.hewing_athletics_bonus(engine, SimpleNamespace(actor_id=ACTOR), None) is None
    context["skill"] = "Athletics"
    engine, actor, _ = _hewing_world(monkeypatch, bitten=False)
    actor.turn_flags[bv.HEWING_FLAG] = bv._turn_key(engine, actor)
    assert bv.hewing_athletics_bonus(engine, SimpleNamespace(actor_id=ACTOR), None) is None


def test_bone_axe_follow_up_expires_at_the_start_of_the_next_turn(monkeypatch):
    engine, actor, _ = _hewing_world(monkeypatch)
    actor.turn_flags[bv.HEWING_FLAG] = bv._turn_key(engine, actor)
    engine.state.current_slot_index = 1
    assert bv.hewing_athletics_bonus(engine, SimpleNamespace(actor_id=ACTOR), None) is None


# ===================================================================== BRS1F13/R: printed combat clauses
def _event(kind, source, actor_id, **payload):
    return SimpleNamespace(event_type=kind, source_definition_id=source, actor_id=actor_id, payload=payload,
                           transaction_id="tx")


def test_tempered_motion_compiles_all_four_printed_clauses():
    """Athletics: the Focus regain is a real trigger, not a missing event."""
    from pathlib import Path
    riders = json.loads((Path(__file__).resolve().parents[1] / "authority" / "body_refining" / "variant_riders.json").read_text())
    clauses = riders["variants"]["tianxia.brvariant.athletics.tempered-motion"]
    assert [clauses[str(i)]["automation"] for i in range(4)] == ["compiled"] * 4
    effects = {rider["effect"] for index in ("1", "2", "3") for rider in clauses[index]["riders"]}
    assert effects == {"falling_reduction", "check_advantage", "speed_on_stamina"}


def test_coordinated_movement_grant_arms_tempered_motion(monkeypatch):
    """The engine's own RESOURCE_GAINED for Coordinated Movement applies the printed benefits."""
    rows, _ = variants(sphere("tianxia.sphere.athletics"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    bv.tempered_motion_focus(engine, _event("RESOURCE_GAINED", bv.COORDINATED_FOCUS_SOURCE, ACTOR,
                                           resource_id=bv.FOCUS, gained=1))
    falling = next(c for c in actor.conditions.values() if c.condition_id == bv.FALLING_CONDITION)
    assert falling.expires_on == "START_OF_SELF_NEXT_TURN"
    check = next(c for c in actor.conditions.values() if c.condition_id == bv.CHECK_CONDITION)
    assert check.data["rule"] == {"check_mode": {"Athletics": "ADVANTAGE"}}
    assert actor.turn_flags[bv.TEMPERED_SPEED_FLAG] == bv._turn_key(engine, actor)

    # The falling reduction is 5 x Proficiency Bonus, applied after ordinary defenses.
    assert bv.tempered_falling_damage(engine, actor, 20, None, None) == {"amount": 20 - 5 * bv._pb(engine, ACTOR)}

    # Speed +5 only after this same turn spends Stamina.
    assert bv.rider_speed(engine, actor) is None
    bv.note_stamina_spend(engine, "RESOURCE_SPENT", {"actor_id": ACTOR, "payload": {"resource_id": bv.STAMINA, "amount": 1}})
    assert bv.rider_speed(engine, actor) == 5
    engine.state.round_number = 2
    engine.state.current_slot_index = 1
    assert bv.rider_speed(engine, actor) is None, "the Speed benefit lasts only the turn that spent the Stamina"

    # The one Athletics check spends the Advantage.
    monkeypatch.setattr("combat.ext.roll_context.check_skill_receipts", lambda kwargs: [(ACTOR, {}, "Athletics")])
    bv.consume_tempered_check(engine, "CHECK_ROLLED", {})
    check = next(c for c in actor.conditions.values() if c.condition_id == bv.CHECK_CONDITION)
    assert check.data["used"] is True and check.data["rule"] == {}


def test_tempered_motion_is_inert_without_the_variant():
    actor = make_actor()
    engine = make_engine([], actor)
    bv.tempered_motion_focus(engine, _event("RESOURCE_GAINED", bv.COORDINATED_FOCUS_SOURCE, ACTOR,
                                           resource_id=bv.FOCUS, gained=1))
    assert actor.conditions == {} and not actor.turn_flags


def test_berserker_batter_advantage_is_consumed_by_the_next_batter_attack_only():
    """Berserker clause 3: the guard-zero Advantage belongs to the next Batter attack."""
    rows, _ = variants(sphere("tianxia.sphere.berserker"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", {"actor_id": ACTOR, "payload": {"pending_after": 0, "spend": 1}})
    assert bv._has_condition(actor, bv.BATTER_CONDITION)

    other = SimpleNamespace(actor=actor, engine=engine, typed={"source": "TAL_BERSERKER_HEAVY_SWING"})
    assert bv.batter_advantage(other, None) is None, "an attack that is not Batter does not spend it"
    batter = SimpleNamespace(actor=actor, engine=engine, typed={"source": "TAL_BERSERKER_BATTER"})
    assert bv.batter_advantage(batter, None) == "ADVANTAGE"
    assert not bv._has_condition(actor, bv.BATTER_CONDITION), "spent by that attack"
    assert bv.batter_advantage(batter, None) is None


def test_guard_zero_riders_are_compiled_from_data():
    from pathlib import Path
    riders = json.loads((Path(__file__).resolve().parents[1] / "authority" / "body_refining" / "variant_riders.json").read_text())
    assert riders["variants"]["tianxia.brvariant.protection.living-bulwark-body"]["5"]["riders"][0]["effect"] == "regain_stamina"
    assert riders["variants"]["tianxia.brvariant.fire.furnace-body"]["6"]["riders"][0]["condition"] == "condition:typed.burning"
    assert riders["variants"]["tianxia.brvariant.sound.bell-bone-circulation"]["2"]["riders"][0]["mark"] == "Resonance"
    assert riders["variants"]["tianxia.brvariant.iron_fist.iron-body-scripture"]["4"]["riders"][0]["effect"] == "free_move"
    assert riders["variants"]["tianxia.brvariant.ash.ashen-body"]["6"]["riders"][0]["effect"] == "remnant"


def test_guard_zero_recovers_stamina_and_applies_the_printed_condition():
    rows, _ = variants(sphere("tianxia.sphere.protection"))
    actor = make_actor(resources={bv.STAMINA: 3})
    engine = make_engine(rows, actor)
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", {"actor_id": ACTOR, "payload": {"pending_after": 0, "spend": 1}})
    assert actor.resources[bv.STAMINA] == 3 + bv._pb(engine, ACTOR)
    before = list(engine.events)
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", {"actor_id": ACTOR, "payload": {"pending_after": 0, "spend": 1}})
    assert engine.events == before, "once per round"

    fire_rows, _ = variants(sphere("tianxia.sphere.fire"))
    attacker = make_actor(entity_id="creature:foe", team_id="team:b")
    fire_engine = make_engine(fire_rows, actor)
    fire_engine.state.actors[attacker.entity_id] = attacker
    bv.rider_guard_zero(fire_engine, "REACTION_RESOLVED", {"actor_id": ACTOR, "payload": {"pending_after": 0, "spend": 1}})
    held = next(c for c in attacker.conditions.values() if c.condition_id == "condition:typed.burning")
    assert held.expires_on == "END_OF_HOLDER_NEXT_TURN"


def test_sound_pulse_save_applies_resonance_only_on_a_failure():
    from combat.typed_executor import mark_condition_id

    rows, _ = variants(sphere("tianxia.sphere.sound"))
    actor = make_actor()
    foe = make_actor(entity_id="creature:foe", team_id="team:b")
    engine = make_engine(rows, actor)
    engine.state.actors[foe.entity_id] = foe
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", {"actor_id": ACTOR, "payload": {"pending_after": 0, "spend": 1}})
    assert any(c.condition_id == mark_condition_id("Resonance", ACTOR) for c in foe.conditions.values())

    saved_engine = make_engine(rows, actor)
    saved_engine.state.actors[foe.entity_id] = foe
    saved_engine._roll_save = lambda *args, **kwargs: SimpleNamespace(total=99)
    foe.conditions.clear()
    bv.rider_guard_zero(saved_engine, "REACTION_RESOLVED", {"actor_id": ACTOR, "payload": {"pending_after": 0, "spend": 1}})
    assert not foe.conditions, "a successful save leaves no Resonance"


def test_iron_fist_guard_reward_grants_five_feet_without_opportunity_attacks():
    rows, _ = variants(sphere("tianxia.sphere.iron_fist"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", {"actor_id": ACTOR, "payload": {"pending_after": 0, "spend": 1}})
    assert actor.movement_remaining_ft == 5 and actor.turn_flags["oa_free_ft"] == 5


def test_ash_guard_reward_leaves_the_ash_spheres_own_remnant(monkeypatch):
    from combat.ext import ash_core, placed

    rows, _ = variants(sphere("tianxia.sphere.ash"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    calls = []
    monkeypatch.setattr("combat.zones.terrain_rules", lambda: {"terrains": {"ash terrain": {"material": "ash"}}})
    monkeypatch.setattr(placed, "place", lambda engine, owner, **kw: calls.append(kw))
    monkeypatch.setattr(placed, "of", lambda engine, tag, owner_id=None: [])
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", {"actor_id": ACTOR, "payload": {"pending_after": 0, "spend": 1}})
    assert calls and calls[0]["tag"] == ash_core.TAG and calls[0]["terrain"] == ["ash terrain"]


def test_once_per_turn_damage_bonuses_use_the_printed_talent_only():
    """Dream Needle and Glass Shard add the key modifier once per turn; an unrelated talent gets nothing."""
    rows, _ = variants(sphere("tianxia.sphere.dreams"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    ctx = SimpleNamespace(engine=engine, actor=actor, typed={"source": "TAL_DREAM_DREAM_NEEDLE"}, numbers={"key_mod": 4})
    assert bv.talent_damage_bonus(ctx, None, {}) == 4
    assert bv.talent_damage_bonus(ctx, None, {}) is None
    engine.state.round_number = 2
    assert bv.talent_damage_bonus(ctx, None, {}) == 4
    assert bv.talent_damage_bonus(SimpleNamespace(engine=engine, actor=actor, typed={"source": "TAL_DREAM_DREAM_SLEEP"},
                                                 numbers={"key_mod": 4}), None, {}) is None

    glass_rows, _ = variants(sphere("tianxia.sphere.glass"))
    glass_engine = make_engine(glass_rows, actor)
    glass = SimpleNamespace(engine=glass_engine, actor=actor, typed={"source": "GLASS_BASE_GLASS_SHARD"}, numbers={"key_mod": 3})
    assert bv.talent_damage_bonus(glass, None, {}) == 3


def test_monkey_link_bonus_does_not_double_count_a_constitution_keyed_damage_roll():
    rows, _ = variants(sphere("tianxia.sphere.monkey_style"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    ctx = SimpleNamespace(engine=engine, actor=actor,
                          typed={"source": "TAL_MONKEY_STYLE_VAULTING_STRIKE"},
                          numbers={"key_mod": 4, "con_mod": 4})
    assert bv.talent_damage_bonus(ctx, None, {}) is None  # already included
    ctx.numbers = {"key_mod": 2, "con_mod": 4}
    assert bv.talent_damage_bonus(ctx, None, {}) == 4


def test_vaulting_strike_trades_its_bonus_die_for_a_d10():
    from combat.gate2_runtime_models import DiceSpec

    rows, _ = variants(sphere("tianxia.sphere.monkey_style"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    ctx = SimpleNamespace(engine=engine, actor=actor, typed={"source": "TAL_MONKEY_STYLE_VAULTING_STRIKE"},
                          weapon_damage_dice=False)
    assert bv.talent_damage_die(ctx, DiceSpec(count=1, sides=8)).sides == 10
    ctx.weapon_damage_dice = True
    assert bv.talent_damage_die(ctx, DiceSpec(count=1, sides=8)) is None


def test_air_gather_current_range_is_ten_feet_shorter_for_a_body_refiner():
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind

    action = ActionDefinition(source_definition_id="AIR_BASE_GATHER_CURRENT", display_name="Gather Current",
                              owner_id=ACTOR, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY", range_ft=30,
                              parameters={"typed": {"source": "AIR_BASE_GATHER_CURRENT", "range_ft": 30}})
    reduced = bv.reduce_talent_range(action, {"owner_sheet": sheet(spheres=["tianxia.sphere.air"])})
    assert reduced.range_ft == 20 and reduced.parameters["typed"]["range_ft"] == 20
    # A character who does not own the Air variant compiles the printed range unchanged.
    assert bv.reduce_talent_range(action, {"owner_sheet": sheet(spheres=[])}) is None


def test_drunken_choice_offers_every_printed_benefit_and_applies_the_answer(monkeypatch):
    import combat.ext.needle as needle

    rows, _ = variants(sphere("tianxia.sphere.drunken_style"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    seen = {}

    def fake_ask(engine, intent, checkpoint, chooser, choice_id, options, **kw):
        seen["options"], seen["labels"] = list(options), dict(kw.get("labels") or {})
        return ["temp_hp"]

    monkeypatch.setattr(needle, "ask", fake_ask)
    ctx = SimpleNamespace(engine=engine, actor=actor, typed={"source": "TAL_DRUNKEN_STYLE_REELING_STEP"},
                          action=SimpleNamespace(display_name="Reeling Step"))
    bv.choice_after_technique(ctx)
    assert seen["options"] == ["temp_hp", "falling", "save"]
    assert all("br_variant" not in label and "tianxia" not in label for label in seen["labels"].values())
    assert ("TEMP_HP", 2) in engine.events
    before = list(engine.events)
    bv.choice_after_technique(ctx)
    assert engine.events == before, "once per turn"


def test_verdant_growth_choice_needs_a_claim_on_the_body(monkeypatch):
    from combat.ext import verdant_chassis

    rows, _ = variants(sphere("tianxia.sphere.verdant_growth"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    asked = []
    monkeypatch.setattr("combat.ext.needle.ask", lambda *a, **k: asked.append(a) or ["temp_hp"])
    bv.choice_at_turn_start(engine, actor)
    assert not asked, "no Living Claim on the body means no printed benefit"
    monkeypatch.setattr(verdant_chassis, "claims",
                        lambda engine, owner: [SimpleNamespace(component={"on": actor.entity_id})])
    bv.choice_at_turn_start(engine, actor)
    assert asked and ("TEMP_HP", 2) in engine.events


def test_force_impact_choice_adds_five_feet_or_the_constitution_modifier(monkeypatch):
    rows, _ = variants(sphere("tianxia.sphere.force"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    answers = iter([["push"], ["damage"]])
    monkeypatch.setattr("combat.ext.needle.ask", lambda *a, **k: next(answers))
    ctx = SimpleNamespace(engine=engine, actor=actor, typed={"source": "TAL_FORCE_BODY_CONDUCTED_IMPACT"},
                          action=SimpleNamespace(display_name="Body-Conducted Impact"), numbers={"con_mod": 3})
    bv.choice_after_technique(ctx)
    assert bv.force_choice_push(ctx, actor, {}, 5) == 10
    engine.state.current_slot_index = 1
    bv.choice_after_technique(ctx)
    assert bv.force_choice_damage(ctx, actor, 5) == 3
    assert bv.force_choice_damage(ctx, actor, 5) is None, "one damage roll"


def test_guard_zero_free_attack_is_a_real_no_action_copy_gated_to_the_round():
    """Barrage: "once per round ... make one ranged weapon attack with a thrown weapon"."""
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind

    attack = ActionDefinition(source_definition_id="action:typed.thrown_knife", display_name="Thrown Knife",
                              owner_id=ACTOR, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY", range_ft=20,
                              parameters={"typed": {"weapon": {"name": "Knife"}, "range_ft": 20,
                                                    "effects": [{"type": "attack", "attack_kind": "ranged"}]}})
    copies = bv.compile_guard_attacks({"owner_sheet": sheet(spheres=["tianxia.sphere.barrage"]), "actions": [attack]})
    assert len(copies) == 1
    copy = copies[0]
    assert copy.economy == EconomyKind.NONE and copy.costs == ()
    assert copy.source_definition_id == "action:typed.thrown_knife+brguard"
    key = copy.parameters["typed"][bv.GUARD_ATTACK]
    actor = make_actor()
    engine = make_engine([], actor)
    engine.action_catalog = {copy.source_definition_id: copy}
    assert bv.guard_attack_available(engine, actor, None, copy) is False
    rows, _ = variants(sphere("tianxia.sphere.barrage"))
    engine.typed_passive_rows[ACTOR] = rows
    bv.rider_guard_zero(engine, "REACTION_RESOLVED", {"actor_id": ACTOR, "payload": {"pending_after": 0, "spend": 1}})
    assert bv.guard_attack_available(engine, actor, None, copy) is True
    bv.spend_guard_attack(engine, actor, "NONE", copy.source_definition_id)
    assert bv.guard_attack_available(engine, actor, None, copy) is False, "one free attack"
