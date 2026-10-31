"""Lane MGR-T14-ling-base-sword-in-hand-1: the printed clauses of SWORD_BASE_SWORD_IN_HAND.

"Sword in Hand - Sword Intent Strike" (APP/authority/typed_mechanics/rules_text.json,
decoded-rules SHA256 a0a89e8d397d3e14ce7d251e82e929df8700ce910f75ea75f5050d6460dd030e):

    Action Type: Action
    Timing Detail: Special Attack
    Range: Sword reach
    Cost: None
    Replace one attack with one Sword weapon attack.
    Hit: Deal normal weapon damage plus:
    1d8 Slashing or Force damage
    Apply Sword Intent until the start of your next turn.
    Choose the damage type when making the attack.

These tests are the clause matrix, driven at the level the clauses live:

  * the printed form of the ability ("Replace one attack with one Sword weapon attack", "Cost: None",
    "Range: Sword reach", "Action Type: Action") is asserted on the COMPILED action the fighter really gets;
  * the printed hit clauses are asserted on a real committed turn through CombatService/TabletopService, then
    again after a cold commit and disk reload, so the persisted Sword Intent is what is being checked;
  * "Choose the damage type when making the attack" is asserted against a target that resists one of the two
    printed types, so a build that hard-coded the first listed type would fail;
  * a fighter that does not own the row is checked to get no button and no Sword Intent.

Nothing here is a direct plug-in call or injected test metadata: every assertion reads the engine's own action
catalog, its own rolls, its own committed events, or its own persisted state.

The row is already fully automated (see the lane report); these tests pin it so a later change that drops a
clause fails here.
"""
from __future__ import annotations

import pytest

from combat import typed_executor as te
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ROOT, sheet  # noqa: F401  (documents where the authority under test is read from)
from tests.hunt12_support import FOE
from tests.hunt12_support import ME as SERVICE_ME
from tests.hunt12_support import candidate, fight, hit_dice, reload, send

MID = "SWORD_BASE_SWORD_IN_HAND"
INTENT = "Sword Intent"
JIAN = "tianxia.mortal.weapon.jian"
SWORD_SPHERE = "tianxia.sphere.sword"
SWORD_KIT = {"starting_kit": {"items": [{"item_id": JIAN, "name": "Jian", "quantity": 1}]}}
ME = "actor:factory.mgrt14.sih"
STRIKE = "Sword in Hand"
JIAN_SWORD_NAME = "Jian (Straight Sword) attack: Sword in Hand"


# ------------------------------------------------------------------ the printed form of the ability
def _strike_action(engine, owner=ME):
    """The fighter's own compiled SWORD_BASE_SWORD_IN_HAND action, exactly as the catalog holds it."""
    rows = [row for row in engine.action_catalog.values()
            if str(row.source_definition_id).endswith(MID) and row.owner_id == owner]
    assert len(rows) == 1, [row.source_definition_id for row in rows]
    return rows[0]


def _service_strike(combat, mid):
    engine = combat._load_session(mid).engine
    action = _strike_action(engine, SERVICE_ME)
    assert action.source_definition_id.startswith("action:typed.")
    return engine, action


def test_sword_in_hand_replaces_one_attack_with_the_wielded_sword_weapon_attack(tmp_path):
    """"Replace one attack with one Sword weapon attack." -- the button IS the wielded Sword's own attack.

    ``typed.delivered_by`` is the compiler's own delivery link (combat/factory_compiler.py), and
    combat/weapon_delivery.py ``weapon_identity`` follows it, so weapon-hit riders, hand occupancy and reach all
    read the physical Sword rather than a bare record id.
    """
    combat, _table, mid = fight(tmp_path, [MID], cl=18, dc=100, kit=SWORD_KIT)
    engine, action = _service_strike(combat, mid)
    typed = (action.parameters or {}).get("typed") or {}

    delivered_by = typed.get("delivered_by")
    assert delivered_by, "'Replace one attack with one Sword weapon attack' needs the delivering weapon action"
    weapon_action = engine.action_catalog[delivered_by]
    assert weapon_action.owner_id == SERVICE_ME
    assert (weapon_action.parameters or {}).get("typed", {}).get("weapon", {}).get("implement_id") == JIAN

    from combat.weapon_delivery import weapon_identity

    assert weapon_identity(engine, action.source_definition_id, typed, action.parameters, owner_id=SERVICE_ME) \
        == delivered_by.split("#", 1)[0], "the strike must resolve to the wielded Sword, not an unarmed packet"

    # and the fighter is offered exactly one such attack, not a generic extra button
    buttons = [c.display_name for c in engine.legal_candidates() if STRIKE in c.display_name]
    assert buttons, "the fighter is never offered Sword in Hand"
    assert all(JIAN_SWORD_NAME in name for name in buttons), buttons


def test_sword_in_hand_is_a_free_action_at_sword_reach(tmp_path):
    """"Action Type: Action", "Range: Sword reach", "Cost: None", "Timing Detail: Special Attack"."""
    combat, _table, mid = fight(tmp_path, [MID], cl=18, dc=100, kit=SWORD_KIT)
    engine, action = _service_strike(combat, mid)
    typed = (action.parameters or {}).get("typed") or {}

    assert action.economy == "ACTION", "Action Type: Action"
    assert list(action.costs) == [], "'Cost: None' means the button spends nothing"
    assert action.attack_count == 1, "Replace ONE attack with one Sword weapon attack"
    assert action.range_ft == 5, "'Range: Sword reach' -- the wielded melee Sword's own reach"

    # "Special Attack": the built row carries the printed delivery shape, not a plain unarmed technique.
    delivery = typed.get("weapon") or {}
    assert delivery.get("attack_delivery") == "melee"


# ------------------------------------------------------------------ the printed hit clauses, through the table
def _strike_once(combat, table, mid, monkeypatch):
    hit_dice(monkeypatch)
    chosen = candidate(combat, mid, lambda c: STRIKE in c.display_name and FOE in c.target_ids
                       and "#" not in c.source_definition_id)
    return send(combat, table, mid, chosen)


def _committed(events, event_type):
    return [e for e in (events.get("events") or []) if e.get("event_type") == event_type]


def test_sword_in_hand_hit_deals_weapon_damage_plus_1d8_and_marks_sword_intent_until_the_start_of_your_next_turn(tmp_path, monkeypatch):
    """"Hit: Deal normal weapon damage plus: 1d8 ... Apply Sword Intent until the start of your next turn."

    Driven through TabletopService.act and re-read from disk, so both committed events and the persisted mark are
    the table's own record rather than a plug-in's return value.
    """
    combat, table, mid = fight(tmp_path, [MID], cl=18, dc=100, kit=SWORD_KIT)
    hp_before = combat._load_session(mid).engine.state.actors[FOE].current_hp
    result = _strike_once(combat, table, mid, monkeypatch)
    assert result["status"] == "COMMITTED"

    engine = reload(tmp_path, mid)  # cold commit + reload; asserts the mechanical replay is a PASS
    rolls = {r.expression for r in engine.rolls if str(r.reason).startswith("DAMAGE:")}
    assert any(e.startswith("1d8") for e in rolls), f"the printed 1d8 was never rolled: {sorted(rolls)}"
    assert any(e.startswith("1d10") for e in rolls), f"the Sword's own weapon damage was never rolled: {sorted(rolls)}"

    # "Deal normal weapon damage PLUS 1d8": two separate commits, the weapon's own first.
    events = combat._load_session(mid).engine
    damage = [r.expression for r in events.rolls if str(r.reason).startswith("DAMAGE:")]
    assert damage.index(next(e for e in damage if e.startswith("1d10"))) < \
        damage.index(next(e for e in damage if e.startswith("1d8"))), damage

    # "Apply Sword Intent until the start of your next turn": present after the cold reload, and expiring on the
    # START of the marker's next turn (combat/gate2_engine.py START_OF_MARKER_NEXT_TURN).
    intents = [c for c in engine.state.actors[FOE].conditions.values() if INTENT.lower().replace(" ", "_") in c.condition_id]
    assert len(intents) == 1, [c.condition_id for c in engine.state.actors[FOE].conditions.values()]
    assert intents[0].expires_on == "START_OF_MARKER_NEXT_TURN", intents[0].expires_on

    packets = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.target_ids == (FOE,)]
    assert len(packets) == 2
    amounts = [int(e.payload["reduced_to"]) for e in packets]
    damage_rolls = [r for r in engine.rolls if str(r.reason).startswith("DAMAGE:")]
    assert amounts == [r.total for r in damage_rolls]
    assert damage_rolls[0].expression.startswith("1d10")
    # Roll records spell the zero modifier as +0. Check the die expression
    # separately from its modifier (dice stores rolled values, not die sizes).
    assert damage_rolls[1].expression in {"1d8", "1d8+0"}
    assert len(damage_rolls[1].dice) == 1
    assert damage_rolls[1].modifier == 0
    assert engine.state.actors[FOE].current_hp == hp_before - sum(amounts)

    from tests.test_lock2_persistence import act

    assert act(table, mid, "end")["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == FOE
    assert te.bears_mark(engine.state.actors[FOE], SERVICE_ME, INTENT)
    assert not te.bears_mark(engine.state.actors[FOE], FOE, INTENT)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == SERVICE_ME
    assert not te.bears_mark(engine.state.actors[FOE], SERVICE_ME, INTENT)


def test_sword_in_hand_chooses_the_damage_type_that_lands():
    """"Choose the damage type when making the attack." -- Slashing or Force.

    combat/typed_executor.py ``choose_damage_type`` is the general seam, and the owner's 2026-09-26 ruling picks the
    type that lands hardest. A target that resists Slashing must therefore receive the 1d8 as Force; a build that
    simply took the first listed type would hand out Slashing and land half of it.
    """
    from tests.hunt24_support import finish_direct_setup

    bundle = compile_character(sheet([MID], cl=18, dc=100, primary="Stamina", score=18, kit=SWORD_KIT),
                               actor_id=ME)
    foe_doc = sheet([], cl=18, dc=100, primary="Stamina", score=18)
    foe_doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
    foe_bundle = compile_character(foe_doc, actor_id=FOE)
    engine = Gate4ControllerEngine(
        ROOT, match_seed="MGRT14", typed_bundles=(bundle, foe_bundle),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    finish_direct_setup(engine)
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    me.resources["resource:core.martial_focus"] = 1
    foe.armor_class = -50
    foe.maximum_hp = foe.current_hp = 1000
    # A real Resistance on the fight's own defence table (combat/typed_reactions.py _defenses), not a roster field:
    # the printed choice reads the same table the damage is later reduced by.
    engine._add_modifier(foe, "test:resist_slashing", "damage_resistance", "SET", "SLASHING", "ALL", expires_on=None)

    from tests.h1_support import script

    original = Gate4ControllerEngine._resolve_attack_spec

    def resolve(engine_self, *args, **kwargs):
        script(engine_self, [18, 8, 8] + [8] * 60)  # an ordinary hit, then 1d10 -> 8 and 1d8 -> 8
        return original(engine_self, *args, **kwargs)

    Gate4ControllerEngine._resolve_attack_spec = resolve
    try:
        candidate_row = next(c for c in engine.legal_candidates()
                             if STRIKE in c.display_name and FOE in c.target_ids)
        engine.execute_intent(ActionIntent(intent_id="sih", decision_id=candidate_row.decision_id,
                                           candidate_id=candidate_row.candidate_id,
                                           state_version=candidate_row.state_version, actor_id=ME,
                                           target_ids=candidate_row.target_ids,
                                           destination=candidate_row.destination))
    finally:
        Gate4ControllerEngine._resolve_attack_spec = original

    committed = [e for e in engine.events if getattr(e, "event_type", "") == "DAMAGE_COMMITTED"]
    types = [str((getattr(e, "payload", None) or {}).get("damage_type")) for e in committed]
    assert types == ["PIERCING", "FORCE"], \
        f"the printed Slashing-or-Force choice ignored the target's Slashing resistance: {types}"
    dealt = [int((getattr(e, "payload", None) or {}).get("reduced_to") or 0) for e in committed]
    assert sum(dealt) == 12 + 8, f"the extra 1d8 was not dealt at full Force: {dealt}"


# ------------------------------------------------------------------ ownership boundary
def test_sword_in_hand_is_absent_for_a_fighter_that_does_not_own_the_row(tmp_path):
    """A typed row is inert for a character that does not own it.

    Sword in Hand is one of the Sword sphere's automatic base abilities, so the control is a fighter that owns no
    Sword sphere at all: the build must offer it no Sword in Hand attack, and nothing may mark it with Sword Intent.
    """
    combat, table, mid = fight(tmp_path, [], cl=18, dc=100, kit=SWORD_KIT)
    engine = combat._load_session(mid).engine
    assert not [row for row in engine.action_catalog.values() if str(row.source_definition_id).endswith(MID)], \
        "a fighter that does not own SWORD_BASE_SWORD_IN_HAND must not be offered its attack"
    assert not [c.display_name for c in engine.legal_candidates() if STRIKE in c.display_name]
    assert not [c for actor in engine.state.actors.values() for c in actor.conditions.values()
                if INTENT.lower().replace(" ", "_") in c.condition_id]


def test_sword_intent_is_marked_by_the_striker_and_belongs_to_them(tmp_path, monkeypatch):
    """Ownership boundary on the mark: the Sword Intent belongs to the fighter who struck, not to any Sword fighter.

    combat/typed_executor.py ``bears_mark`` keys the mark on the marker's entity id, so a second fighter who also owns
    Sword in Hand must not count as the bearer of somebody else's Intent.
    """
    from tests.hunt12_support import candidate as _candidate

    combat, table, mid = fight(tmp_path, [MID], cl=18, dc=100, kit=SWORD_KIT)
    _strike_once(combat, table, mid, monkeypatch)
    engine = reload(tmp_path, mid)
    other = engine.state.actors[FOE].model_copy(deep=True)
    other.entity_id = "actor:factory.other_sword_fighter"
    other.display_name = "Other Sword fighter"
    engine.state.actors[other.entity_id] = other
    assert te.bears_mark(engine.state.actors[FOE], SERVICE_ME, INTENT), \
        "'Apply Sword Intent' -- the striker's own mark is on the target"
    assert not te.bears_mark(engine.state.actors[FOE], other.entity_id, INTENT), \
        "Sword Intent is owned by the fighter who struck; another Sword fighter does not inherit it"
    assert _candidate is not None


# ------------------------------------------------------------------ the printed record itself
def test_sword_in_hand_records_no_gm_work_and_full_coverage():
    """"A printed line the table cannot resolve is KEPT as a GM rider." None is: the row is FULL."""
    from tests import test_riders_c4 as C4

    mechanic = C4.mech(MID)
    assert mechanic["riders"] == [], f"{MID} still records GM rider lines"
    assert mechanic["coverage"] == "FULL"
    assert te.bears_mark  # the mark reader the printed Sword Intent clause is resolved through
