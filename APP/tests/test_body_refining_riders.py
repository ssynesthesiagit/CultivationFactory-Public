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
    base = dict(entity_id=ACTOR, display_name="Body Student", conditions={}, resources={}, resource_maximums={},
                turn_flags={}, active=True, current_hp=20, maximum_hp=40)
    base.update(overrides)
    return Actor(**base)


def make_engine(rows, actor, *, round_number=1, slot=0):
    engine = Actor()
    engine.typed_passive_rows = {actor.entity_id: list(rows)}
    engine.state = SimpleNamespace(round_number=round_number, current_slot_index=slot, zones={},
                                   actors={actor.entity_id: actor})
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
        target.conditions[condition_id] = SimpleNamespace(condition_id=condition_id, data=dict(data or {}),
                                                          source_definition_id=source)
    engine._apply_condition = apply_condition
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


def test_start_of_turn_temporary_hp_is_granted_once_per_fight():
    rows, _ = variants(sphere("tianxia.sphere.flowers"))
    actor = make_actor(current_hp=10, maximum_hp=40)
    engine = make_engine(rows, actor)
    bv.rider_turn_start(engine, actor)
    assert ("TEMP_HP", 2) in engine.events
    assert any(c.condition_id == "condition:typed.br_variant_temp" for c in actor.conditions.values())
    before = list(engine.events)
    bv.rider_turn_start(engine, actor)
    assert engine.events == before
    # Above half maximum HP the printed condition is not met.
    healed = make_actor(current_hp=30, maximum_hp=40)
    healed_engine = make_engine(rows, healed)
    bv.rider_turn_start(healed_engine, healed)
    assert not any(event[0] == "TEMP_HP" for event in healed_engine.events)


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
