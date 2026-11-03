"""MMX116f1: which event a trigger-generated resource is locked to (HUNT 114 #1, review findings 1-3).

The printed rule (``authority/typed_mechanics/rules_text.json``,
``foundation.ancient_desolate_sacred_body_v0_2C.generate_golden_sea_pulse``) is "**A Pulse generated
by an event cannot be spent on that same event**"; ``golden_sea_guard`` and ``refuse_heaven_lock``
require "1 Golden Sea Pulse **from a prior event**".

The fix under test (``combat/ext/prior_event_resources.py``) locks a grant to the **event window** that
produced it: the act, and each attack within it. These tests drive the real compiled fighter, the real
compiled reaction rows and the real event cascade, and they distinguish two attacks in one act from
the two damage packets of one attack -- the distinction the earlier per-act lock got wrong.

  * ``test_the_second_attack_of_one_action_may_spend_the_first_attacks_pulse`` fails on the reviewed
    head (8ea0a843), whose lock ran to the next accepted intent: a valid Golden Sea Guard was refused.
  * ``test_both_damage_packets_of_one_attack_still_share_one_event`` fails on 42e43e14 (HUNT 114 #1
    itself), where the Pulse paid for the very attack that generated it.
  * ``test_a_grant_raised_inside_another_event_hook_is_held_too`` fails on 8ea0a843: Gate 4 delivers a
    child event only to ``nested=True`` subscribers, so a ``pressure.generate`` called from inside an
    event hook (combat/ext/foundation_resources.py) reached nothing.
These are synthetic engine-event checks, not persisted table or nested-return tests.
Real table pause/commit/reload coverage is in test_solfmmx116r2_resources.py.
"""

from copy import deepcopy

from combat import ext as ext_package
from combat import typed_reactions
from combat.canonical import canonical_sha256

from combat.gate2_engine import Gate2Engine
from combat.gate4_engine import Gate4ControllerEngine
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from tests.test_pressure import FOUNDATION, ME
from tests.test_zones import SHEET

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PULSE = "resource:foundation.golden_sea_pulse"
GUARD = "foundation.ancient_desolate_sacred_body_v0_2C.golden_sea_guard"


def _engine():
    bundle = compile_character({**SHEET, "foundation": FOUNDATION}, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="MMX116f1", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN],
                                                 "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    engine.state.current_actor_id = AN
    return engine


def _attack(engine, *, rolls=True, damage=10):
    """One attack of the current act: the attack is rolled, the reaction window answers, the damage
    commits (which is when a Foundation trigger generates a Pulse).

    ``rolls=False`` is a second damage packet of the attack already rolling, not a new attack.
    """
    if rolls:
        engine._append_event("ATTACK_ROLLED", "test:strike", actor_id=AN, target_ids=(ME,),
                             payload={"roll_id": "roll:test", "modified_total": 99, "provisional_hit": True})
    engine._append_event("REACTION_WINDOW_OPENED", "test:hit", actor_id=AN, target_ids=(ME,),
                         payload={"checkpoint": "DAMAGE_APPLICATION", "pending_damage": damage})
    pending = typed_reactions.on_damage(engine, engine.state.actors[ME], damage, 0, "test:hit", AN)
    engine._append_event("DAMAGE_COMMITTED", "test:hit", actor_id=AN, target_ids=(ME,),
                         payload={"hp_damage": max(0, pending), "temporary_hp_absorbed": 0})
    return pending


def _guard_resolved(engine):
    return any(event.event_type == "REACTION_RESOLVED" and event.source_definition_id == GUARD
               for event in engine.events)


def _digest(engine):
    return canonical_sha256(engine.state.model_dump(mode="json"))


# ------------------------------------------------------------------ finding 1: one act, two attacks
def test_the_second_attack_of_one_action_may_spend_the_first_attacks_pulse():
    """A Multiattack's second attack is a prior event for the Pulse its first attack generated.

    Without the per-event window the lock ran to the next accepted intent, so Golden Sea Guard was
    refused here and the fighter lost a reaction the printed rule allows.
    """
    engine = _engine()
    me = engine.state.actors[ME]
    assert me.resources[PULSE] == 0

    _attack(engine)  # first attack: no Pulse exists yet
    assert me.resources[PULSE] == 1, "the first hit generated the Pulse"

    _attack(engine)  # second attack of the SAME action: a prior event now
    assert _guard_resolved(engine), "a prior event's Pulse must pay for the next attack of the same action"
    assert me.resources[PULSE] == 0


# ------------------------------------------------------------------ finding 1 (reversed): one attack
def test_both_damage_packets_of_one_attack_still_share_one_event():
    """HUNT 114 #1 itself: the second packet of ONE attack is that same event, not a prior one."""
    engine = _engine()
    me = engine.state.actors[ME]

    _attack(engine)
    assert me.resources[PULSE] == 1, "the hit generated the Pulse"

    _attack(engine, rolls=False)  # the same attack's other damage packet
    assert not _guard_resolved(engine), "the Pulse must not pay for the attack that generated it"
    assert me.resources[PULSE] == 1, "a refused reaction spends nothing"


def test_a_later_act_spends_it_too():
    """The lock is not a loss: the next act's own attack is a prior event as well."""
    engine = _engine()
    me = engine.state.actors[ME]
    _attack(engine)

    engine._append_event("INTENT_ACCEPTED", "test:next_act", actor_id=AN, target_ids=(), payload={})
    _attack(engine)

    assert _guard_resolved(engine)
    assert me.resources[PULSE] == 0


def test_a_second_synthetic_attack_inside_the_same_action_is_its_own_window():
    """Sequential synthetic attack windows; this does not establish nested-return behavior."""
    engine = _engine()
    me = engine.state.actors[ME]
    _attack(engine)
    assert me.resources[PULSE] == 1

    _attack(engine)  # the retaliatory strike, which rolls its own attack inside the same act
    assert _guard_resolved(engine), "a retaliatory attack is a prior event for the Pulse that provoked it"
    assert me.resources[PULSE] == 0


# --------------------------------------------------------------------------- finding 2: nested grants
def test_a_grant_raised_inside_another_event_hook_is_held_too():
    """A grant produced inside an event hook is still a grant, whichever call path produced it.

    Gate 4 hands a child event only to ``nested=True`` subscribers, so without the opt-in a
    ``pressure.generate`` inside a movement/attack event hook (combat/ext/foundation_resources.py)
    reached no subscriber and the Pulse was spendable on the very event that produced it.
    """
    engine = _engine()
    me = engine.state.actors[ME]
    grant = {"resource_id": PULSE, "gained": 1, "current": 1, "source": "test:nested"}

    def _raise_it(engine_, event_type, kwargs):
        """A second subscriber that grants the pool from inside the cascade, as a trigger does."""
        if event_type == "ATTACK_ROLLED" and kwargs.get("actor_id") == AN:
            me.resources[PULSE] = 1
            engine_._append_event("RESOURCE_GAINED", "test:nested", actor_id=ME, target_ids=(ME,), payload=grant)

    ext_package.hook("event", nested=True)(_raise_it)
    try:
        assert _raise_it in ext_package._NESTED_HOOKS["event"]
        _attack(engine)  # the grant happens inside the ATTACK_ROLLED cascade of this attack
        assert me.resources[PULSE] == 1
        _attack(engine, rolls=False)  # the same attack's other packet
        assert not _guard_resolved(engine), "a grant made inside a hook must be held like any other"
    finally:
        ext_package._HOOKS["event"].remove(_raise_it)
        ext_package._NESTED_HOOKS["event"].discard(_raise_it)
        ext_package._HOOK_PRIORITIES.pop((("event", _raise_it)), None)


# ------------------------------------------------------------------------------- inertness and saving
def test_an_ordinary_pool_no_trigger_generates_is_never_held():
    """Inert for everything that is not a trigger-generated pool: an ordinary Qi payment is untouched."""
    engine = _engine()
    me = engine.state.actors[ME]
    qi = next(rid for rid in me.resources if rid.endswith("qi"))
    engine._append_event("ATTACK_ROLLED", "test:strike", actor_id=AN, target_ids=(ME,),
                         payload={"roll_id": "roll:test", "provisional_hit": True})
    me.resources[qi] = me.resources[qi] + 1
    engine._append_event("RESOURCE_GAINED", "test", actor_id=ME, target_ids=(ME,),
                         payload={"resource_id": qi, "gained": 1, "current": me.resources[qi]})
    engine._append_event("REACTION_WINDOW_OPENED", "test:qi", actor_id=AN, target_ids=(ME,),
                         payload={"checkpoint": "DAMAGE_APPLICATION", "pending_damage": 1})
    assert typed_reactions._holds(engine, me, qi, 1), "an ordinary pool is never held"


def test_transient_holds_are_absent_from_match_state_and_fresh_engines():
    """Source/state-shape check only: these fresh engines are not loaded from a saved fight."""
    engine = _engine()
    me = engine.state.actors[ME]
    before = _digest(engine)

    _attack(engine)
    assert me.resources[PULSE] == 1, "the Pulse really was granted, and is held for its own event"

    # No hold field is in MatchState. Generation changes the pool and its ordinary expiry clock.
    assert "pressure_generated_this_act" not in repr(engine.state.model_dump(mode="json"))
    after = _digest(engine)
    reloaded = Gate2Engine(ROOT, match_seed="MMX116f1")
    assert "_prior_event_holds" not in reloaded.__dict__ and "_prior_event_window" not in reloaded.__dict__, \
        "a fresh engine carries no lock: the lock is resolution-local, not saved"
    assert after != before, "the granted pool is a real change to the fight"
    granted = {key: value for key, value in me.resources.items() if me.resources[key]}
    assert set(granted) >= {PULSE}

    # A fresh engine with a manually seeded pool has no lock (not a persistence test).
    rebuilt = Gate4ControllerEngine(ROOT, match_seed="MMX116f1", typed_bundles=(
        compile_character({**SHEET, "foundation": FOUNDATION}, actor_id=ME),),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    rebuilt_me = rebuilt.state.actors[ME]
    rebuilt_me.resources[PULSE] = 1  # a save taken after a hit already carries the Pulse
    assert typed_reactions._holds(rebuilt, rebuilt_me, PULSE, 1), \
        "a freshly constructed engine with a seeded pool holds nothing"


def test_a_fighter_who_owns_no_generate_row_is_never_held():
    """Inert for fighters without the Foundation row: the hook asks the actor's own generate rows."""
    from combat.ext import prior_event_resources

    engine = _engine()
    me = engine.state.actors[ME]
    me.resources[PULSE] = 1
    assert prior_event_resources._triggers(engine, me, PULSE), "the Foundation fighter owns the row"
    plain = Gate2Engine(ROOT, match_seed="MMX116f1")
    plain.state = deepcopy(engine.state)
    plain.typed_passive_rows = {}
    assert not prior_event_resources._triggers(plain, plain.state.actors[ME], PULSE)
    plain.__dict__["_prior_event_holds"] = {(ME, PULSE): {1}}
    plain.__dict__["_prior_event_window"] = 1
    assert prior_event_resources.prior_event_only(plain, plain.state.actors[ME], PULSE, 1, {}) is None, \
        "without a generate row the grant is not the Foundation's and nothing is held"
    assert prior_event_resources.prior_event_only(engine, object(), PULSE, 1, {}) is None, \
        "a value that is not a creature in this fight is left to another subscriber"
