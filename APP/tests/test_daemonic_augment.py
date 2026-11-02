"""Daemonic Augment: payment alternatives, named pools, the state-carrying options, and one turn gate.

The state-carrying options are unit-tested on their hooks with synthetic fakes, so each claim is checked alone:
the +5 ft extension, the Resistance type prompt (never in preview, never a second bypass), and the mark's
Essence (on first damage, never at mark time). The compiled record is checked from the authority file.
"""

import json
from types import SimpleNamespace

import pytest

from combat import factory_compiler, pending_damage, typed_executor
from combat.ext import daemonic_augment as aug
from combat.ext import needle

AUGMENT = "TAL_DAEMONIC_CULTIVATION_DAEMONIC_AUGMENT"
ESSENCE = "resource:named.devoured_essence"
ESSENCE_NAME = "Devoured Essence"
FOUNDATION = [{"name": ESSENCE_NAME, "resource_id": ESSENCE}]
OPTIONS = ("Bonus Damage", "Concentration Disadvantage", "Increase Movement", "Deny Reactions",
           "Ignore Resistance", "Mark Creature")


class Actor:
    def __init__(self, entity_id, **resources):
        self.entity_id = entity_id
        self.display_name = entity_id
        self.active = True  # a living combatant, as ActorState reports it to the defense path
        self.turn_flags = {}
        self.resources = dict(resources)
        self.resource_maximums = {}
        self.conditions = {}
        self.modifiers = {}
        self.damage_resistances = ()
        self.concentration = None
        self.turns_started = 1
        self.passive_ids = ()
        self.augment_ids = ()
        self.action_ids = ()
        self.reaction_ids = ()
        from combat.gate2_runtime_models import Position
        self.position = Position(x=0, y=0)


class Engine:
    def __init__(self, *actors):
        self.state = SimpleNamespace(actors={a.entity_id: a for a in actors}, round_number=1,
                                     current_actor_id=actors[0].entity_id, zones={}, terminal_result=None)
        self.events = []
        self.gains = []
        self.typed_passive_rows = {}
        self.typed_reaction_rows = {}
        self.action_catalog = {}  # typed_reactions._typed reads the source packet from here

    def _append_event(self, event_type, source, **kwargs):
        self.events.append((event_type, source, kwargs))

    def _on_battlefield(self, actor):
        return bool(getattr(actor, "active", False))

    def damage_context(self):
        return None  # no attack provenance: the Immunity probe and the packet read it like the real engine

    def _gain_resource(self, actor, resource, amount, source):
        self.gains.append((actor.entity_id, resource, amount, source))
        actor.resources[resource] = actor.resources.get(resource, 0) + amount

    def _apply_condition(self, target, condition, source, owner, expires_on=None):
        target.conditions[condition] = SimpleNamespace(condition_id=condition, owner=owner)

    def _remove_condition(self, target, condition, source):
        target.conditions.pop(condition, None)


def _marker(kind, **extra):
    return {"type": kind, "modifier_once": AUGMENT, "modifier_once_period": "turn", **extra}


def _record():
    with open(factory_compiler.TYPED_AUTHORITY, encoding="utf-8") as handle:
        return json.load(handle)["mechanics"][AUGMENT]


# --- payment alternatives: the printed three-way cost reaches modifier.cost ---------------------------

def test_the_printed_three_way_cost_is_three_alternatives_in_the_record():
    cost = _record()["modifier"]["cost"]
    assert [[(part["resource"], part["amount"]) for part in way] for way in cost] == [
        [("cp", 1)], [("stamina", 1)], [("devoured_essence", 1)]]


def test_an_owned_named_pool_resolves_to_its_resource_id():
    modifier = {"cost": [[{"resource": "devoured_essence", "amount": 1}]]}
    assert factory_compiler._modifier_payments(modifier, [], "qi", [], FOUNDATION) == [
        (0, [(ESSENCE, 1)], "1 Devoured Essence")]


def test_an_unowned_named_pool_is_not_offered():
    modifier = {"cost": [[{"resource": "devoured_essence", "amount": 1}]]}
    assert factory_compiler._modifier_payments(modifier, [], "qi", [], []) == []


def test_an_unowned_pool_drops_only_its_own_way():
    modifier = {"cost": [[{"resource": "cp", "amount": 1}], [{"resource": "devoured_essence", "amount": 1}]]}
    assert [n for n, _c, _w in factory_compiler._modifier_payments(modifier, [], "qi", [], [])] == [0]
    assert [n for n, _c, _w in factory_compiler._modifier_payments(modifier, [], "qi", [], FOUNDATION)] == [0, 1]


# --- the six options and the stray top-level rows -----------------------------------------------------

def test_the_talent_has_no_top_level_effect_of_its_own():
    assert _record()["effects"] == []


def test_all_six_options_are_one_once_per_turn_modifier():
    record = _record()["modifier"]
    assert [option["label"] for option in record["options"]] == list(OPTIONS)
    assert record["limit"] == "once_per_turn"


# --- once-per-turn across options ---------------------------------------------------------------------

def test_any_option_closes_the_gate_for_every_other_option():
    actor = Actor("actor")
    engine = Engine(actor)
    movement, resistance, mark = (_marker("forced_movement_bonus"), _marker("daemonic_augment_resistance"),
                                  _marker("daemonic_augment_mark"))
    assert not aug._spent(engine, actor, resistance)
    aug._spend(engine, actor, movement)
    assert aug._spent(engine, actor, resistance) and aug._spent(engine, actor, mark)


# --- Increase Movement: +5 ft extends the trigger, once -----------------------------------------------

def test_increase_movement_extends_the_triggering_push_once_per_turn():
    actor, foe = Actor("actor"), Actor("foe")
    engine = Engine(actor, foe)
    typed = {"effects": [_marker("forced_movement_bonus", distance_ft=5)]}
    ctx = SimpleNamespace(engine=engine, actor=actor, typed=typed, damage_cache={})
    row = {"type": "forced_movement"}
    assert aug._movement_bonus(ctx, foe, row) == 5
    assert aug._movement_bonus(ctx, foe, {"type": "forced_movement"}) is None
    assert aug._movement_bonus(ctx, foe, row) is None


# --- Ignore Resistance: asked at the packet, ordinary Resistance only, never in preview ----------------

def _resist_typed():
    return {"effects": [_marker("daemonic_augment_resistance"), {"type": "damage", "damage_types": ["poison"]}]}


def test_resistance_is_never_asked_in_preview(monkeypatch):
    target, actor = Actor("foe"), Actor("actor")
    target.modifiers["r"] = SimpleNamespace(target_field="damage_resistance", value="POISON")
    engine = Engine(actor, target)
    monkeypatch.setattr(pending_damage, "current", lambda _engine: None)
    monkeypatch.setattr(needle, "ask", lambda *a, **k: pytest.fail("asked in preview"))
    assert aug._ignore_resistance(engine, "POISON", _resist_typed(), actor.entity_id, target) is None


def test_resistance_asks_the_type_at_the_packet_and_pierces_ordinary_resistance_once(monkeypatch):
    target, actor = Actor("foe"), Actor("actor")
    target.modifiers["r"] = SimpleNamespace(target_field="damage_resistance", value="POISON")
    engine = Engine(actor, target)
    asked = []
    monkeypatch.setattr(pending_damage, "current", lambda _engine: SimpleNamespace(transaction_id=1, source_actor_id=actor.entity_id))
    monkeypatch.setattr(needle, "ask", lambda *a, **k: asked.append(a[5]) or ["POISON"])
    assert aug._ignore_resistance(engine, "POISON", _resist_typed(), actor.entity_id, target) is True
    assert asked == [["POISON"]]


def test_immunity_probe_is_read_only_and_switches_off_resistance_bypass(monkeypatch):
    from combat import typed_reactions
    actor, target = Actor("actor"), Actor("foe")
    engine = Engine(actor, target)
    seen = {}

    def fake_defenses(engine, target, damage_type, source_definition_id, source_actor_id, **kwargs):
        seen["bypass_off"] = engine.__dict__.get("_immunity_probe") is True
        return {"immune": True}

    monkeypatch.setattr(typed_reactions, "_defenses", fake_defenses)
    monkeypatch.setattr(typed_reactions, "additional_defenses", lambda *a, **k: [])
    assert typed_reactions.target_immune(engine, target, "POISON", {}, actor.entity_id,
                                         source_definition_id="WEAPON_SOURCE") is True
    assert seen == {"bypass_off": True}
    assert engine.__dict__.get("_immunity_probe") is False  # restored after the probe


def test_an_immune_target_with_ordinary_resistance_is_never_asked_or_spent(monkeypatch):
    # Ignore Resistance pierces ordinary Resistance only (rules text: "never pierces Immunity"). The target has both.
    from combat import typed_reactions
    target, actor = Actor("foe"), Actor("actor")
    target.modifiers["r"] = SimpleNamespace(target_field="damage_resistance", value="POISON")
    target.modifiers["i"] = SimpleNamespace(target_field="damage_immunity", value="POISON")
    engine = Engine(actor, target)
    marker = _marker("daemonic_augment_resistance")
    monkeypatch.setattr(pending_damage, "current", lambda _engine: SimpleNamespace(
        transaction_id=1, source_actor_id=actor.entity_id, source_id="WEAPON_SOURCE"))
    monkeypatch.setattr(needle, "ask", lambda *a, **k: pytest.fail("asked for an Immune target"))
    assert aug._ignore_resistance(engine, "POISON", _resist_typed(), actor.entity_id, target) is None
    aug._settle_resistance(engine, target, "POISON", "WEAPON_SOURCE", actor.entity_id,
                           {"resist": False, "resistance_suppressed": True})
    assert not actor.turn_flags  # no spend
    assert not [e for e in engine.events if e[0] == "PASSIVE_TRIGGERED" and e[1] == AUGMENT]  # no Augment trigger
    assert not aug._spent(engine, actor, marker)  # the gate stays open for the other options


def test_resistance_never_applies_without_ordinary_resistance(monkeypatch):
    target, actor = Actor("foe"), Actor("actor")  # no Resistance: nothing to ignore (Immunity is never reached here)
    engine = Engine(actor, target)
    monkeypatch.setattr(pending_damage, "current", lambda _engine: SimpleNamespace(transaction_id=1, source_actor_id=actor.entity_id))
    monkeypatch.setattr(needle, "ask", lambda *a, **k: pytest.fail("asked with nothing to ignore"))
    assert aug._ignore_resistance(engine, "POISON", _resist_typed(), actor.entity_id, target) is None


# --- Ignore Resistance: the printed "or weapon damage" share ------------------------------------------

def _weapon_typed():
    """A slashing weapon attack carrying the Ignore Resistance option (a longsword; an Unarmed Strike is Bludgeoning)."""
    return {"weapon": {"damage_type": "SLASHING", "damage_types": ["SLASHING"]},
            "effects": [_marker("daemonic_augment_resistance"), {"type": "damage", "weapon_damage": True}]}


def _weapon_packet(engine, actor, target):
    """The packet context gate2_engine commits for a weapon hit, with its real fields."""
    engine._pending_damage_context = SimpleNamespace(
        amount=7, damage_type="SLASHING", pressure_kind="damage", source_id="WEAPON_SOURCE",
        source_actor_id=actor.entity_id, target_id=target.entity_id, hostile=True, source_wounded=False,
        source_flags=frozenset(), event_sequence=0, transaction_id=1, resources_before=(), hp_before=0)


def _weapon_fight(*modifiers):
    target, actor = Actor("foe"), Actor("actor")
    for name, field, value in modifiers:
        target.modifiers[name] = SimpleNamespace(target_field=field, value=value)
    engine = Engine(actor, target)
    engine.action_catalog["WEAPON_SOURCE"] = SimpleNamespace(parameters={"typed": _weapon_typed()})
    _weapon_packet(engine, actor, target)
    return engine, actor, target


def test_the_printed_weapon_damage_share_ignores_ordinary_physical_resistance(monkeypatch):
    # The printed list ends "... Force, or weapon damage": a weapon packet names Slashing (never "weapon"), so the
    # share has to resolve on that physical type or the option is paid for and halves nothing.
    from combat import typed_reactions
    engine, actor, target = _weapon_fight(("r", "damage_resistance", "SLASHING"))
    asked = []
    monkeypatch.setattr(needle, "ask", lambda *a, **k: asked.append(a[5]) or [a[5][0]])
    assert typed_reactions.damage_factor(engine, target, "SLASHING", "WEAPON_SOURCE", actor.entity_id) == 1.0
    assert asked == [["SLASHING"]]  # the weapon's own physical type, the printed share


def test_the_weapon_damage_share_never_pierces_immunity(monkeypatch):
    from combat import typed_reactions
    engine, actor, target = _weapon_fight(("r", "damage_resistance", "SLASHING"),
                                          ("i", "damage_immunity", "SLASHING"))
    monkeypatch.setattr(needle, "ask", lambda *a, **k: pytest.fail("asked for an Immune target"))
    assert typed_reactions.damage_factor(engine, target, "SLASHING", "WEAPON_SOURCE", actor.entity_id) == 0.0


def test_only_the_printed_damage_types_are_offered():
    # A trigger that deals a type outside the printed list (Lightning) is offered only its printed types.
    typed = {"effects": [_marker("daemonic_augment_resistance"),
                         {"type": "damage", "damage_types": ["lightning", "fire"]}]}
    assert aug._damage_types(typed) == ("FIRE",)


# --- Mark Creature: Essence on first damage, not at mark time -----------------------------------------

def _with_essence(actor):
    """The owner's Devoured Essence pool, as the sphere grants it (a named pool with its own maximum)."""
    actor.resources[ESSENCE] = 0
    actor.resource_maximums[ESSENCE] = 10
    return actor


def _mark_ctx(engine, actor, typed, targets):
    return SimpleNamespace(engine=engine, actor=actor, typed=typed, targets=targets, target=targets[0], damage_cache={})


def test_mark_with_no_damage_places_no_mark_and_no_essence():
    # A trigger that deals no damage (a save-only or missed rider) leaves nothing marked to last a whole turn.
    actor, foe = Actor("actor"), Actor("foe")
    engine = Engine(actor, foe)
    typed = {"effects": [_marker("daemonic_augment_mark")]}
    ctx = _mark_ctx(engine, actor, typed, [foe])
    aug._mark(ctx, {"type": "daemonic_augment_mark"})
    aug._mark_pays_on_damage(ctx, foe, 0)  # a zero-damage packet is not damage
    assert foe.conditions == {}
    assert engine.gains == []
    assert not any(event[0] == "PASSIVE_TRIGGERED" for event in engine.events)


def test_mark_with_no_essence_pool_invents_no_maximum(monkeypatch):
    actor, foe = Actor("actor"), Actor("foe")  # no Devoured Essence pool: nothing printed to gain into
    engine = Engine(actor, foe)
    monkeypatch.setattr(typed_executor, "bears_mark", lambda target, owner, mark=None: True)
    ctx = SimpleNamespace(engine=engine, actor=actor, damage_cache={})
    aug._mark_pays_on_damage(ctx, foe, 4)
    assert engine.gains == [] and ESSENCE not in actor.resources and actor.resource_maximums == {}


def test_mark_lands_on_the_creature_the_trigger_damages(monkeypatch):
    actor, foe, bystander = _with_essence(Actor("actor")), Actor("foe"), Actor("bystander")
    engine = Engine(actor, foe, bystander)
    typed = {"effects": [_marker("daemonic_augment_mark")]}
    ctx = _mark_ctx(engine, actor, typed, [bystander])
    aug._mark(ctx, {"type": "daemonic_augment_mark"})  # the mark row runs before the damage it rides on
    aug._mark_pays_on_damage(ctx, foe, 4)  # a different creature, damaged by the trigger, takes the mark
    assert foe.conditions and not bystander.conditions
    assert engine.gains == []  # the marking damage pays no Essence
    assert actor.turn_flags.get(aug.modifier_key(_marker("daemonic_augment_mark")))
    aug._mark_pays_on_damage(ctx, foe, 2)  # the next damage from the owner gains the one Essence
    assert engine.gains == [(actor.entity_id, ESSENCE, 1, AUGMENT)]


def test_mark_after_damage_lands_on_the_damaged_creature():
    actor, foe = Actor("actor"), Actor("foe")
    engine = Engine(actor, foe)
    typed = {"effects": [_marker("daemonic_augment_mark")]}
    ctx = _mark_ctx(engine, actor, typed, [foe])
    aug._mark_pays_on_damage(ctx, foe, 3)  # damage resolves first
    aug._mark(ctx, {"type": "daemonic_augment_mark"})
    assert foe.conditions


def test_first_damage_to_the_marked_creature_gains_one_essence_once_a_round(monkeypatch):
    actor, foe = _with_essence(Actor("actor")), Actor("foe")
    engine = Engine(actor, foe)
    monkeypatch.setattr(typed_executor, "bears_mark", lambda target, owner, mark=None: True)
    ctx = SimpleNamespace(engine=engine, actor=actor, damage_cache={})
    aug._mark_pays_on_damage(ctx, foe, 4)
    aug._mark_pays_on_damage(ctx, foe, 4)
    assert engine.gains == [(actor.entity_id, ESSENCE, 1, AUGMENT)]


def test_a_later_activation_is_asked_again_even_if_a_freed_intent_id_is_reused(monkeypatch):
    # Two activations, two intent objects. Simulate CPython reusing the first intent's id() for the second: the answer
    # is keyed on the intent object itself, so the second activation still asks and applies its own type.
    target, actor = Actor("foe"), Actor("actor")
    target.modifiers["r"] = SimpleNamespace(target_field="damage_resistance", value="POISON")
    target.modifiers["a"] = SimpleNamespace(target_field="damage_resistance", value="ACID")
    engine = Engine(actor, target)
    typed = {"effects": [_marker("daemonic_augment_resistance"),
                         {"type": "damage", "damage_types": ["poison", "acid"]}]}
    pending = SimpleNamespace(transaction_id=1, source_actor_id=actor.entity_id, source_id="WEAPON_SOURCE")
    answers, asked = iter([["POISON"], ["ACID"]]), []
    monkeypatch.setattr(needle, "ask", lambda *a, **k: asked.append(a[5]) or next(answers))
    monkeypatch.setattr(aug, "id", lambda _obj: 42, raising=False)  # every intent looks like the same id()
    engine._active_intent = object()
    assert aug._choice(engine, pending, typed, target, "POISON") == "POISON"
    engine._active_intent = object()  # a second activation: must ask again, not reuse "POISON"
    assert aug._choice(engine, pending, typed, target, "ACID") == "ACID"
    assert len(asked) == 2
    assert aug._choice(engine, pending, typed, target, "ACID") == "ACID"  # same activation: no new question
    assert len(asked) == 2


def test_the_executor_runs_a_zero_damage_mark_without_closing_the_augment():
    # The executor must not spend the once-per-turn gate for a Mark that places nothing (no damage landed).
    from combat.typed_executor import Context, run_effects
    actor, foe = Actor("actor"), Actor("foe")
    engine = Engine(actor, foe)
    row = _marker("daemonic_augment_mark")
    action = SimpleNamespace(action_id="daemonic_augment", name="Daemonic Augment", owner_id=actor.entity_id,
                             source_definition_id="WEAPON_SOURCE", parameters={"typed": {"effects": [row]}})
    run_effects(Context(engine, actor, action, None, {"effects": [row]}, [foe], foe, {}), [row])
    assert foe.conditions == {} and not actor.turn_flags
    assert not aug._spent(engine, actor, row)
