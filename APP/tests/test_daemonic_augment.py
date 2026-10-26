"""Daemonic Augment: payment alternatives, named pools, the state-carrying options, and one turn gate.

The state-carrying options are unit-tested on their hooks with synthetic fakes, so each claim is checked alone:
the +5 ft extension, the Resistance type prompt (never in preview, never a second bypass), and the mark's
Essence (on first damage, never at mark time). The compiled record is checked from the authority file.
"""

import copy
import json
from types import SimpleNamespace

import pytest

from combat import factory_compiler, pending_damage, typed_executor
from combat.ext import daemonic_augment as aug
from combat.ext import needle
from tests.test_zones import SHEET as SYNTHETIC_SHEET

AUGMENT = "TAL_DAEMONIC_CULTIVATION_DAEMONIC_AUGMENT"
ESSENCE = "resource:named.devoured_essence"
ESSENCE_NAME = "Devoured Essence"
FOUNDATION = [{"name": ESSENCE_NAME, "resource_id": ESSENCE}]
OPTIONS = ("Bonus Damage", "Concentration Disadvantage", "Increase Movement",
           "Ignore Resistance", "Mark Creature")


class Actor:
    def __init__(self, entity_id, **resources):
        self.entity_id = entity_id
        self.display_name = entity_id
        self.turn_flags = {}
        self.resources = dict(resources)
        self.resource_maximums = {}
        self.conditions = {}
        self.modifiers = {}
        self.damage_resistances = ()


class Engine:
    def __init__(self, *actors):
        self.state = SimpleNamespace(actors={a.entity_id: a for a in actors}, round_number=1,
                                     current_actor_id=actors[0].entity_id)
        self.events = []
        self.gains = []

    def _append_event(self, event_type, source, **kwargs):
        self.events.append((event_type, source, kwargs))

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


def test_the_five_automated_options_are_one_once_per_turn_modifier():
    record = _record()["modifier"]
    assert [option["label"] for option in record["options"]] == list(OPTIONS)
    assert record["limit"] == "once_per_turn"


# --- G1: the Augment reaches any sphere technique, not only attacks -----------------------------------

def test_the_augment_reaches_any_sphere_technique():
    record = _record()["modifier"]
    assert record["scope"] == "any_sphere_technique"
    assert record.get("any_sphere") is True


# --- G4: the Augment is offered on weapon attacks and Unarmed Strikes too, not only sphere techniques -----

def test_the_augment_scope_is_composable_kinds_for_attacks_and_sphere_techniques():
    record = _record()["modifier"]
    assert set(record["scope_kinds"]) == {"any_sphere_technique", "any_attack"}


def _compiled_augment_hosts():
    # Use a public synthetic sheet at the compiler boundary rather than the
    # history-dependent rider audit fixture.
    sheet = copy.deepcopy(SYNTHETIC_SHEET)
    sheet["spheres_and_talents"] = {
        "sphere_record_ids": ["tianxia.sphere.daemonic_cultivation", "tianxia.sphere.lightning"],
        "learned_talent_record_ids": [AUGMENT],
        "automatic_sphere_component_record_ids": _lightning_base_abilities(),
    }
    sheet["equipment"] = [{"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}
    ]}}]
    return factory_compiler.compile_character(sheet, actor_id="actor:factory.daemonic-augment-g4")


def _lightning_base_abilities():
    with open(factory_compiler.TYPED_AUTHORITY, encoding="utf-8") as handle:
        mechanics = json.load(handle)["mechanics"]
    return [key for key, row in mechanics.items()
            if row.get("sphere_id") == "tianxia.sphere.lightning" and row.get("kind") == "base_ability"]


def _compiled_augment_names(bundle):
    return [row["display_name"] for row in bundle["action_catalog"]
            if " + Daemonic Augment" in row["display_name"]]


def _unowned_compiled_augment_names():
    sheet = copy.deepcopy(SYNTHETIC_SHEET)
    sheet["spheres_and_talents"] = {
        "sphere_record_ids": ["tianxia.sphere.daemonic_cultivation", "tianxia.sphere.lightning"],
        "learned_talent_record_ids": [],
        "automatic_sphere_component_record_ids": _lightning_base_abilities(),
    }
    sheet["equipment"] = [{"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}
    ]}}]
    bundle = factory_compiler.compile_character(sheet, actor_id="actor:factory.daemonic-augment-control")
    return _compiled_augment_names(bundle)


def test_the_augment_is_offered_on_a_weapon_attack_unarmed_strike_and_another_sphere_technique():
    bundle = _compiled_augment_hosts()
    names = _compiled_augment_names(bundle)
    hosts = {name.split(" + Daemonic Augment")[0] for name in names}
    assert "Fu (Short Axe) attack" in hosts     # a weapon attack
    assert "Unarmed Strike" in hosts            # an Unarmed Strike
    assert "Lightning Lash: Charge" in hosts    # a sphere technique from another sphere
    assert len(names) == len(set(names))         # no duplicate variants
    assert _unowned_compiled_augment_names() == []


# --- G3: Deny Reactions is manual, never an automated option ------------------------------------------

def test_deny_reactions_is_not_an_automated_option():
    labels = [option["label"] for option in _record()["modifier"]["options"]]
    assert "Deny Reactions" not in labels
    assert "reaction_denied" not in json.dumps(_record()["modifier"])


def test_g4_removes_only_the_native_attack_rider_and_keeps_manual_and_needs_system_clauses():
    riders = _record()["riders"]
    assert len(riders) == 2
    assert riders[0].startswith("Daemonic Augment has typed technique variants. Checking that its chosen benefit")
    assert "older native attacks" not in riders[0]
    assert riders[1].startswith("Deny Reactions is NEEDS-SYSTEM:")


# --- G2: weapon damage is a printed Ignore Resistance target ------------------------------------------

def test_ignore_resistance_names_weapon_damage_in_the_record():
    option = next(o for o in _record()["modifier"]["options"] if o["label"] == "Ignore Resistance")
    assert "weapon" in option["effects"][0]["damage_types"]


def _weapon_typed(damage_type="SLASHING"):
    return {"effects": [_marker("daemonic_augment_resistance"),
                        {"type": "attack", "attack_kind": "weapon",
                         "on_hit": [{"type": "damage", "weapon_damage": True}]}],
            "weapon": {"damage_type": damage_type}}


def test_a_physical_weapon_packet_maps_to_the_weapon_option():
    typed = _weapon_typed("SLASHING")
    assert aug._option_kind("SLASHING", typed) == "WEAPON"
    assert aug._option_kind("BLUDGEONING", typed) == "WEAPON"
    assert aug._option_kind("FIRE", typed) is None


def test_weapon_resistance_is_asked_and_ignored_for_a_physical_packet(monkeypatch):
    target, actor = Actor("foe"), Actor("actor")
    target.modifiers["r"] = SimpleNamespace(target_field="damage_resistance", value="SLASHING")
    engine = Engine(actor, target)
    asked = []
    monkeypatch.setattr(pending_damage, "current", lambda _engine: SimpleNamespace(transaction_id=2, source_actor_id=actor.entity_id))
    monkeypatch.setattr(needle, "ask", lambda *a, **k: asked.append(a[5]) or ["WEAPON"])
    assert aug._ignore_resistance(engine, "SLASHING", _weapon_typed("SLASHING"), actor.entity_id, target, ordinary=True) is True
    assert asked == [["WEAPON"]]


# --- G5: Resistance never pierces Immunity ------------------------------------------------------------

def test_ignore_resistance_never_pierces_immunity(monkeypatch):
    target, actor = Actor("foe"), Actor("actor")
    target.modifiers["i"] = SimpleNamespace(target_field="damage_immunity", value="POISON")
    engine = Engine(actor, target)
    monkeypatch.setattr(pending_damage, "current", lambda _engine: SimpleNamespace(transaction_id=3, source_actor_id=actor.entity_id))
    monkeypatch.setattr(needle, "ask", lambda *a, **k: pytest.fail("asked to pierce Immunity"))
    assert aug._ignore_resistance(engine, "POISON", _resist_typed(), actor.entity_id, target) is None


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
    assert aug._ignore_resistance(engine, "POISON", _resist_typed(), actor.entity_id, target, ordinary=True) is True
    assert asked == [["POISON"]]


def test_resistance_never_applies_without_ordinary_resistance(monkeypatch):
    target, actor = Actor("foe"), Actor("actor")  # no Resistance: nothing to ignore (Immunity is never reached here)
    engine = Engine(actor, target)
    monkeypatch.setattr(pending_damage, "current", lambda _engine: SimpleNamespace(transaction_id=1, source_actor_id=actor.entity_id))
    monkeypatch.setattr(needle, "ask", lambda *a, **k: pytest.fail("asked with nothing to ignore"))
    assert aug._ignore_resistance(engine, "POISON", _resist_typed(), actor.entity_id, target) is None


# --- Mark Creature: Essence on first damage, not at mark time -----------------------------------------

def test_marking_gains_no_essence(monkeypatch):
    actor, foe = Actor("actor"), Actor("foe")
    engine = Engine(actor, foe)
    typed = {"effects": [_marker("daemonic_augment_mark")]}
    ctx = SimpleNamespace(engine=engine, actor=actor, typed=typed, targets=[foe], target=foe)
    aug._mark(ctx, {"type": "daemonic_augment_mark"})
    assert engine.gains == []
    assert foe.conditions


def test_first_damage_to_the_marked_creature_gains_one_essence_once_a_round(monkeypatch):
    actor, foe = Actor("actor"), Actor("foe")
    engine = Engine(actor, foe)
    monkeypatch.setattr(typed_executor, "bears_mark", lambda target, owner, mark=None: True)
    ctx = SimpleNamespace(engine=engine, actor=actor)
    aug._mark_pays_on_damage(ctx, foe, 4)
    aug._mark_pays_on_damage(ctx, foe, 4)
    assert engine.gains == [(actor.entity_id, ESSENCE, 1, AUGMENT)]


# --- Ignore Resistance settles at commit: damage_defended notifies, final_damage spends and logs --------

@pytest.fixture
def resist_packet(monkeypatch):
    from combat import typed_reactions
    target, actor = Actor("foe"), Actor("actor")
    target.modifiers["r"] = SimpleNamespace(target_field="damage_resistance", value="POISON")
    engine = Engine(actor, target)
    typed = _resist_typed()
    monkeypatch.setattr(typed_reactions, "_typed", lambda _engine, _source: typed)
    monkeypatch.setattr(pending_damage, "current", lambda _engine: SimpleNamespace(transaction_id=7, source_actor_id=actor.entity_id))
    monkeypatch.setattr(needle, "ask", lambda *a, **k: ["POISON"])
    assert aug._ignore_resistance(engine, "POISON", typed, actor.entity_id, target, ordinary=True) is True
    return SimpleNamespace(engine=engine, actor=actor, target=target, typed=typed)


def _suppressed_packet(p, source="src"):
    aug._record_resistance(p.engine, p.target, "POISON", source, p.actor.entity_id,
                           {"resist": False, "resistance_suppressed": True})


def test_damage_defended_asks_nothing_and_spends_nothing(resist_packet, monkeypatch):
    monkeypatch.setattr(needle, "ask", lambda *a, **k: pytest.fail("asked in damage_defended"))
    _suppressed_packet(resist_packet)
    assert not resist_packet.actor.turn_flags
    assert resist_packet.engine.events == []


def test_final_damage_spends_the_gate_and_writes_one_fight_log_entry_at_commit(resist_packet):
    p = resist_packet
    _suppressed_packet(p)
    marker = _marker("daemonic_augment_resistance")
    answer = aug._settle_resistance(p.engine, p.target, 5, "POISON", "src", p.actor.entity_id, None)
    assert answer["reduction"] == 0 and callable(answer["settle"])
    assert not aug._spent(p.engine, p.actor, marker)  # nothing is paid before the packet commits
    answer["settle"](0)
    assert aug._spent(p.engine, p.actor, marker)
    assert [event[0] for event in p.engine.events] == ["PASSIVE_TRIGGERED"]
    assert "Poison" in p.engine.events[0][2]["payload"]["trigger"]
    # the once-per-turn gate: a second packet this turn gets no receipt and no second entry
    assert aug._settle_resistance(p.engine, p.target, 5, "POISON", "src", p.actor.entity_id, None) is None


def test_no_receipt_means_no_spend_and_no_entry(resist_packet):
    p = resist_packet
    assert aug._settle_resistance(p.engine, p.target, 5, "POISON", "src", p.actor.entity_id, None) is None
    assert not aug._spent(p.engine, p.actor, _marker("daemonic_augment_resistance"))
    assert p.engine.events == []


def test_a_packet_that_still_has_resistance_records_no_receipt(resist_packet):
    p = resist_packet
    aug._record_resistance(p.engine, p.target, "POISON", "src", p.actor.entity_id,
                           {"resist": True, "resistance_suppressed": True})
    assert aug._settle_resistance(p.engine, p.target, 5, "POISON", "src", p.actor.entity_id, None) is None



def test_a_second_packet_this_turn_is_not_claimed_once_the_gate_is_spent(resist_packet):
    p = resist_packet
    _suppressed_packet(p)
    aug._settle_resistance(p.engine, p.target, 5, "POISON", "src", p.actor.entity_id, None)["settle"](0)
    assert aug._spent(p.engine, p.actor, _marker("daemonic_augment_resistance"))
    assert aug._ignore_resistance(p.engine, "POISON", p.typed, p.actor.entity_id, p.target, ordinary=True) is None


def test_penetration_suppression_is_not_attributed_to_the_augment(resist_packet, monkeypatch):
    p = resist_packet
    monkeypatch.setattr(pending_damage, "current", lambda _engine: SimpleNamespace(transaction_id=8, source_actor_id=p.actor.entity_id))
    # Suppressed by something else (no Augment claim for transaction 8): no receipt, no spend, no entry.
    aug._record_resistance(p.engine, p.target, "POISON", "src", p.actor.entity_id,
                           {"resist": False, "resistance_suppressed": True})
    assert aug._settle_resistance(p.engine, p.target, 5, "POISON", "src", p.actor.entity_id, None) is None
    assert not aug._spent(p.engine, p.actor, _marker("daemonic_augment_resistance"))
    assert p.engine.events == []


def test_the_claim_needs_the_engine_to_have_found_ordinary_resistance(monkeypatch):
    target, actor = Actor("foe"), Actor("actor")  # the engine published no ordinary-Resistance decision
    engine = Engine(actor, target)
    monkeypatch.setattr(pending_damage, "current", lambda _engine: SimpleNamespace(transaction_id=3, source_actor_id=actor.entity_id))
    monkeypatch.setattr(needle, "ask", lambda *a, **k: pytest.fail("asked without ordinary Resistance"))
    assert aug._ignore_resistance(engine, "POISON", _resist_typed(), actor.entity_id, target) is None
    assert not engine.__dict__.get("_daemonic_augment_claims")


# --- Review fix 1: the ordinary-Resistance decision is a hook argument, never an engine flag ---------------

def test_defenses_publishes_no_engine_flag_and_passes_the_decision_to_the_hook(monkeypatch):
    """Fails on the old code: _defenses wrote engine.__dict__["_resistance_ordinary_now"] around the bypass call."""
    from combat import typed_reactions
    from combat import ext as ext_pkg
    target, actor = Actor("foe"), Actor("actor")
    target.modifiers["r"] = SimpleNamespace(target_field="damage_resistance", value="POISON")
    engine = Engine(actor, target)
    seen = {}

    def fake_resistance_ignored(eng, kind, typed, source_actor_id, tgt, ordinary=False):
        seen["flag_present"] = "_resistance_ordinary_now" in eng.__dict__
        seen["ordinary"] = ordinary
        return False

    monkeypatch.setattr(typed_reactions, "_resistance_ignored", fake_resistance_ignored)
    typed_reactions._defenses(engine, target, "POISON", None, actor.entity_id)
    assert seen == {"flag_present": False, "ordinary": True}
    assert "_resistance_ordinary_now" not in engine.__dict__
    assert "_resistance_ordinary_now" not in open(typed_reactions.__file__).read()


def test_the_bypass_hook_receives_the_ordinary_decision_as_an_argument(monkeypatch):
    from combat import typed_reactions
    from combat import ext as ext_pkg
    target, actor = Actor("foe"), Actor("actor")
    engine = Engine(actor, target)
    calls = []

    def fake_run(name, *args, **kwargs):
        calls.append((name, kwargs))
        return [False]

    monkeypatch.setattr(ext_pkg, "has", lambda name: name == "resistance_ignored")
    monkeypatch.setattr(ext_pkg, "run", fake_run)
    typed_reactions._resistance_ignored(engine, "POISON", _resist_typed(), actor.entity_id, target, ordinary=True)
    assert calls == [("resistance_ignored", {"ordinary": True})]
