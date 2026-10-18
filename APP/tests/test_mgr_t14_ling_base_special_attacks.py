"""MGR-T14-ling-base-special-attacks-1: the whole printed clauses of BRUTE_BASE_SPECIAL_ATTACKS and
WRESTLING_BASE_SPECIAL_ATTACKS, proven on a real table (compile_character -> Gate4ControllerEngine ->
legal_candidates -> execute_intent), never by calling the plug-in directly.

  "#### Special Attacks
   When a talent says it is a Special Attack, replace one attack when you take the Attack action
   unless the talent explicitly uses a different Action Type."
   (Brute) / "When a Wrestling talent says it is a Special Attack, replace one attack when taking the
   Attack action unless the talent explicitly uses a different Action Type." (Wrestling)

Producer: APP/combat/ext/special_attacks.py (compile_actions / action_completed / candidate_allowed /
technique_used). Which talents qualify is read from the printed rules text
(APP/authority/typed_mechanics/rules_text.json), never from ids, and the guard uses the compiled
candidate economy, which is what the printed "Action Type:" line compiles to.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from combat.gate2_runtime_models import ActionIntent
from tests.equipment_readiness import ready_weapon

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "tests"))

SW = importlib.import_module("test_review_sw-athletics")

ME, AN = SW.ME, SW.AN
EXTRA_ATTACK = ["tianxia.path.body_refining.feature.extra_attack"]
AXES = SW.AXE_KIT["starting_kit"]["items"]
BRUTE, WRESTLING, ATHLETICS = "tianxia.sphere.brute", "tianxia.sphere.wrestling", SW.ATHLETICS
PIN = "TAL_WRESTLING_PIN_2"


def _flag(actor):
    from combat.ext.special_attacks import FLAG

    return int(actor.turn_flags.get(FLAG) or 0)


def _names(engine):
    """Observe legal options without restoring any of the actor's spent budget."""
    return {c.display_name for c in engine.legal_candidates() if c.actor_id == ME}


def _rest(engine):
    return sorted(n for n in _names(engine) if n.endswith("(rest of the Attack action)"))


def _use(engine, name, target=AN):
    """Submit an actually legal candidate with the current action budget intact."""
    candidates = [c for c in engine.legal_candidates()
                  if c.actor_id == ME and c.display_name.split(" at ")[0] == name
                  and (target is None or not c.target_ids or target in c.target_ids)]
    assert candidates, f"{name!r} is not legal; legal: {sorted(_names(engine))}"
    candidate = candidates[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(
        intent_id=f"special-attacks-{engine.state.event_sequence}",
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=ME,
        target_ids=candidate.target_ids, destination=candidate.destination,
        option_ids=candidate.option_ids,
    ))
    return engine.events[before:]


def _bundle(sphere, talents=(), items=(), cl=10, features=()):
    """Compile the same real sheet without importing a private historical test file."""
    sheet = SW._sheet(sphere, list(talents), {"starting_kit": {"items": list(items)}}, cl=cl)
    if features:
        sheet["path_and_subpath"]["path_feature_record_ids"] = list(features)
    return SW.compile_character(sheet, actor_id=ME)


def _fight(sphere, talents=(), items=(), cl=10, features=()):
    engine = SW._engine(_bundle(sphere, talents, items, cl, features), foe_hp=400)
    # Equipment setup happens before the economy under test, through legal Draw.
    ready_weapon(engine, "Fu (Short Axe) attack", ME)
    return engine, engine.state.actors[ME], engine.state.actors[AN]


def _end_turn(engine):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "End turn")
    engine.execute_intent(ActionIntent(
        intent_id=f"special-attacks-end-{engine.state.event_sequence}",
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids,
    ))
    return engine.state.current_actor_id


def _grapple_on_prior_turn(engine, me, foe):
    foe.saving_throws.update(STR=-100, DEX=-100)
    _use(engine, "Grapple")
    assert "condition:typed.grappled" in {c.condition_id for c in foe.conditions.values()}
    assert not me.action_available
    assert _end_turn(engine) == AN
    assert _end_turn(engine) == ME
    assert me.action_available
    assert "condition:typed.grappled" in {c.condition_id for c in foe.conditions.values()}


# -------------------------------------------------------------------------------------- the two rows own their printed text
def test_both_rows_are_printed_base_abilities_granted_with_their_sphere_and_read_from_their_printed_text():
    """Ownership/acquisition: the catalog grants both rows with the sphere (automatic, not a talent choice) and keeps the exact
    printed wording as player rules text; recognition of "is a Special Attack" comes from that printed text, not from an id list."""
    from combat.ext import special_attacks

    catalog = json.loads((APP / "catalog_authority" / "cat3" / "generated" / "catalog_authority.v1.json").read_text(encoding="utf-8"))
    rows = {r["candidate_record_id"]: r for r in catalog["sphere_base_ability_authority"]}
    for key, printed in (("BRUTE_BASE_SPECIAL_ATTACKS", "When a talent says it is a Special Attack, replace one attack when you take "
                          "the Attack action unless the talent explicitly uses a different Action Type."),
                         ("WRESTLING_BASE_SPECIAL_ATTACKS", "When a Wrestling talent says it is a Special Attack, replace one attack when "
                          "taking the Attack action unless the talent explicitly uses a different Action Type.")):
        row = rows[key]
        assert row["automatic_grant"] is True and row["counts_as_talent_choice"] is False and row["owner_removable"] is False, key
        assert printed in row["full_exact_source_text"] and printed in row["player_rules_text"], key
        assert key in special_attacks.special_ids(), key  # the base rule is itself a printed Special Attack rule
    # The talent side is read from printed text, so a Wrestling talent that says so is covered without any id list here.
    assert PIN in special_attacks.special_ids()


# -------------------------------------------------------------------------------------- Wrestling: replace one attack
def test_wrestling_pin_replaces_one_attack_of_the_attack_action_and_the_rest_still_follows():
    """Pin prints "Action Type: Action" + "Timing Detail: Special Attack" and targets a creature you have Grappled. At CL 10 with
    Extra Attack the Attack action has 2 attacks: Pin spends one and the remaining weapon attack stays available this turn."""
    engine, me, foe = _fight(WRESTLING, talents=[PIN], items=AXES, cl=10, features=EXTRA_ATTACK)
    catalog = {row["display_name"]: row for row in _bundle(WRESTLING, [PIN], AXES, cl=10, features=EXTRA_ATTACK)["action_catalog"]}
    pin = catalog["Pin"]
    assert pin["parameters"]["typed"]["source"] == PIN  # provenance is the printed talent, not an injected replacement marker
    assert pin["parameters"].get("replaces_attack") is None
    _grapple_on_prior_turn(engine, me, foe)
    assert _rest(engine) == [] and _flag(me) == 0  # nothing is replaced before the special attack is used
    _use(engine, "Pin", target=AN)
    assert not me.action_available, "Pin spends the original Attack action"
    assert _flag(me) == 1 and _rest(engine), "Pin must leave the other attack of the Attack action"
    assert "Fu (Short Axe) attack" not in _names(engine), "another full Attack action is unavailable"
    events = _use(engine, _rest(engine)[0])
    assert sum(e.event_type == "ATTACK_ROLLED" for e in events) == 1
    assert not me.action_available
    assert _flag(me) == 0 and _rest(engine) == []  # one attack replaced, not the whole action
    assert "Fu (Short Axe) attack" not in _names(engine)


def test_without_extra_attack_the_special_attack_is_the_whole_attack_action():
    """One attack per Attack action: there is nothing left to replace, so no extra buttons appear."""
    engine, me, foe = _fight(WRESTLING, talents=[PIN], items=AXES, cl=10)
    _grapple_on_prior_turn(engine, me, foe)
    _use(engine, "Pin", target=AN)
    assert not me.action_available
    assert _flag(me) == 0 and _rest(engine) == []


def test_the_replaced_attack_does_not_carry_into_the_next_turn():
    """The replacement lasts for the rest of this Attack action only ("...replace one attack when you take the Attack action")."""
    engine, me, foe = _fight(WRESTLING, talents=[PIN], items=AXES, cl=10, features=EXTRA_ATTACK)
    _grapple_on_prior_turn(engine, me, foe)
    _use(engine, "Pin", target=AN)
    assert _flag(me) == 1
    _end_turn(engine)
    assert _end_turn(engine) == ME
    assert _flag(me) == 0 and _rest(engine) == []


def test_a_character_with_no_special_attack_gains_no_replacement_buttons():
    """Wrong-owner control: the plug-in is inert for a character who owns no printed Special Attack rule."""
    bundle = _bundle(ATHLETICS, items=AXES, cl=10, features=EXTRA_ATTACK)
    assert not any("(rest of the Attack action)" in row["display_name"] for row in bundle["action_catalog"])
    engine, me, foe = _fight(ATHLETICS, items=AXES, cl=10, features=EXTRA_ATTACK)
    _use(engine, "Fu (Short Axe) attack")
    assert _flag(me) == 0 and _rest(engine) == []


# -------------------------------------------------------------------------------------- the printed exception
def test_an_option_offered_with_a_different_action_type_does_not_replace_an_attack():
    """"unless the talent explicitly uses a different Action Type": Brute Maneuvers prints "As an Action or Bonus Action" and its row is a
    printed Special Attack row, but the Bonus Action button is compiled with the Bonus Action economy, so it replaces nothing."""
    from combat.ext import special_attacks

    maneuvers = "BRUTE_BASE_BRUTE_MANEUVERS"
    assert maneuvers in special_attacks.special_ids()  # recognized from printed text, so the guard is what decides
    engine, me, foe = _fight(BRUTE, items=AXES, cl=10, features=EXTRA_ATTACK)
    kinds = {c.display_name: c.kind for c in engine.legal_candidates() if "Overrun" in c.display_name}
    assert kinds.get("Overrun (Bonus Action)") is not None and "bonus" in str(kinds["Overrun (Bonus Action)"]).lower()
    _use(engine, "Overrun (Bonus Action)", target=AN)
    assert me.action_available, "Bonus Action Overrun must leave the Action available"
    assert not me.bonus_action_available, "Overrun spends its Bonus Action"
    assert _flag(me) == 0 and _rest(engine) == [], "a different Action Type must not consume an attack of the Attack action"
    assert "Fu (Short Axe) attack" in _names(engine), "the ordinary Attack action is untouched"
    assert "Overrun (Bonus Action)" not in _names(engine)
    assert me.action_available and not me.bonus_action_available, "queries must preserve the budget"


@pytest.mark.parametrize("sphere,talents,first", [(BRUTE, (), "Brutal Shove"), (WRESTLING, (PIN,), "Pin")])
def test_the_base_row_itself_costs_nothing_and_the_replacement_attacks_cost_nothing_either(sphere, talents, first):
    """Cost clauses: neither printed rule row has a cost, an action or a duration - it is a rule, so it never appears as a button and never
    spends anything. The attacks it leaves behind are free too: their compiled economy is NONE."""
    mechanics = SW._mechanics()
    for key in ("BRUTE_BASE_SPECIAL_ATTACKS", "WRESTLING_BASE_SPECIAL_ATTACKS"):
        row = mechanics[key]
        assert row["kind"] == "base_ability" and row["coverage"] == "FULL" and row["riders"] == [], key
        assert row["activation"]["economy"] == "passive" and row["cost"] == [] and row["effects"] == [], key
        assert row["duration"]["kind"] == "instant" and row["duration"]["concentration"] is False, key
    features = EXTRA_ATTACK
    engine, me, foe = _fight(sphere, talents=talents, items=AXES, cl=10, features=features)
    if first == "Pin":
        _grapple_on_prior_turn(engine, me, foe)
    assert not any("Special Attacks" in n for n in _names(engine)), "the printed rule is not an action of its own"
    _use(engine, first)
    rest = _rest(engine)
    assert rest, "the Attack action still has an attack left"
    economies = {row.economy for row in engine.action_catalog.values() if row.display_name in rest}
    assert economies == {"NONE"}, f"the replaced attack must cost nothing, got {economies}"
    # (the talent's own printed Action Type is what spends its action; the rule row spends nothing at all)
