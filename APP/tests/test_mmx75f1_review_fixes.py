"""MMX75f1: the review fixes to MMX75's log wording and d20 attribution.

The pre-merge review of MMX75 asked for four corrections:

1. The "an attack's own roll mode" branch matched *any* self-targeted roll-mode
   field, so a defensive effect (Guardian Spirit Posture disadvantages the next
   attack *against* its owner) and a target-restricted one (Vex helps only
   against one named creature) were printed as if they disadvantaged the owner's
   own attack roll -- the wrong recipient, and an unrestricted benefit.
2. ``user_id`` was written into every ``D20_REWRITTEN`` payload, so a producer
   that does not supply it still recorded a new ``user_id: null`` key and changed
   the serialized event of an unchanged producer.
3. Nothing covered the production attribution: the earlier tests built rewrite
   events with ``user_id`` already present, so deleting the plumbing would leave
   them green. These tests drive the real service, commit the fight, reload it,
   and compare the recorded payload against the base-commit key set.
4. The optional ``d20_bonus`` ``user_id`` was accepted but neither documented nor
   validated on that hook.
"""
import pytest

from combat.gate5_service import CombatService
from combat.history_feed import format_history_feed
from tests.h1_support import ROOT

ACTORS = {"a": "Wolf", "b": "Tabik Damu"}
DEFINITIONS = {"action:typed.0a11.bite": "Bite", "action:typed.0a66.guard": "Guardian Spirit Posture",
               "action:typed.0a77.vex": "Vex"}
GUARD, VEX = "action:typed.0a66.guard", "action:typed.0a77.vex"


def feed(*events):
    return [row["summary"] for row in format_history_feed(
        list(events), [], pre_state=None, post_state={},
        actor_names=dict(ACTORS), definition_names=dict(DEFINITIONS))]


def modifier(record, owner="a", target="a"):
    """A real MODIFIER_APPLIED event carrying the recorded modifier snapshot."""
    record = {**record, "target_id": target, "source_actor_id": owner}
    return {"event_type": "MODIFIER_APPLIED", "actor_id": owner, "target_ids": [target],
            "source_definition_id": record["source_definition_id"],
            "payload": {**record, "gate3_modifier_after": record}}


# ------------------------------------------------------------------ finding 1

def test_a_defensive_roll_mode_still_says_the_attacks_it_receives():
    """Guardian Spirit Posture stamps incoming_attack_mode on the creature it
    guards -- the owner, in the self-targeted case. It disadvantages the next
    attack *against* the owner. Reading it as the owner's own attack roll names
    the wrong recipient, which is the whole point of the finding."""
    (line,) = feed(modifier({
        "modifier_id": "m1", "target_field": "incoming_attack_mode", "operation": "SET",
        "value": "DISADVANTAGE", "applies_to": "NEXT_ATTACK",
        "expires_on": "START_OF_SOURCE_NEXT_TURN", "source_definition_id": GUARD}))
    assert "disadvantage on the next attack roll against them" in line, line
    assert "from Guardian Spirit Posture" in line, line
    # It is not the wolf's own attack roll, and it is not an unrestricted effect.
    assert "is made with" not in line, line
    assert "on the attack roll" not in line, line
    assert "their next attack roll" not in line, line


def test_a_defensive_roll_mode_on_an_ally_names_that_creature_as_the_recipient():
    """The same defensive effect applied to an ally reads about that ally."""
    (line,) = feed(modifier({
        "modifier_id": "m1", "target_field": "incoming_attack_mode", "operation": "SET",
        "value": "DISADVANTAGE", "applies_to": "NEXT_ATTACK",
        "expires_on": "START_OF_SOURCE_NEXT_TURN", "source_definition_id": GUARD},
        owner="a", target="b"))
    assert line.startswith("Tabik Damu: disadvantage on the next attack roll against them"), line
    assert "is made with" not in line, line


def test_a_target_restricted_roll_mode_still_names_the_creature_it_applies_to():
    """Vex stamps attack_mode_vs on the attacker, so it is self-targeted like a
    strike mode -- but the value names the one creature it helps against. Dropping
    that target would promise an unrestricted benefit, so the restriction must
    survive and the next-attack scope must survive with it."""
    (line,) = feed(modifier({
        "modifier_id": "m2", "target_field": "attack_mode_vs", "operation": "SET",
        "value": "ADVANTAGE:b", "applies_to": "NEXT_ATTACK",
        "expires_on": "END_OF_SOURCE_TURN_AT:2", "source_definition_id": VEX}))
    assert "advantage on their next attack roll against Tabik Damu from Vex" in line, line
    # "next attack roll" is the wolf's own, so this is not a defensive effect...
    assert "against them" not in line, line
    # ...and the named target is not dropped.
    assert "their next attack roll against " in line, line


def test_a_target_restricted_roll_mode_keeps_its_target_without_a_next_attack_scope():
    """The same Vex modifier with no "next attack" clock keeps the permanent scope."""
    (line,) = feed(modifier({
        "modifier_id": "m2", "target_field": "attack_mode_vs", "operation": "SET",
        "value": "ADVANTAGE:b", "applies_to": "ALWAYS",
        "expires_on": "UNTIL_REMOVED", "source_definition_id": VEX}))
    assert "advantage on attack rolls against Tabik Damu from Vex" in line, line
    assert "next attack roll" not in line, line


def test_the_own_roll_mode_wording_is_still_used_for_a_real_strike():
    """The fix narrows the branch, it does not remove it: an attack's own roll
    mode (what typed_executor.add_strike_mode stamps on the attacker) is still
    attributed to the attack rather than to the ability acting on its own user."""
    (line,) = feed(modifier({
        "modifier_id": "m3", "target_field": "attack_mode", "operation": "SET",
        "value": "DISADVANTAGE", "applies_to": "NEXT_ATTACK",
        "expires_on": "CONSUMED", "source_definition_id": DEFINITIONS and "action:typed.0a11.bite"}))
    assert line == "Wolf's Bite is made with Disadvantage on the attack roll; until used."


# ------------------------------------------------------------------ finding 2

def test_a_producer_that_does_not_name_a_user_records_the_base_event_shape():
    """Stabilizing Circuit supplies a bonus with no user_id, exactly as it did
    before this lane. The recorded payload must keep the base commit's key set
    exactly -- no new ``user_id: null``. This checks the payload shape and bonus,
    not complete event or final-state equality against another version."""
    from tests.test_riders_c11 import CIRCUIT, _stable_fight

    engine, me = _stable_fight()
    before = len(engine.events)
    engine._concentration_check(me, 10)
    bonus = [e for e in engine.events[before:]
             if e.event_type == "D20_REWRITTEN" and e.source_definition_id == CIRCUIT]
    assert len(bonus) == 1, "the bonus producer did not fire"
    assert set(bonus[0].payload) == {"operation", "bonus", "original", "result"}
    assert "user_id" not in bonus[0].payload
    # And the event still carries everything the replay and the log need.
    assert bonus[0].payload["operation"] == "bonus"
    assert bonus[0].payload["bonus"] == 4


# ------------------------------------------------------------------ finding 3

def test_an_ally_rewrite_records_its_user_across_a_commit_and_reload(monkeypatch, tmp_path):
    """hunt86 H86-11: the creature whose roll is rewritten is often not the one
    who used the ability. Drive that through the real table, commit, reload, and
    check both the recorded user and the rendered line -- so removing
    ``answer["user_id"]`` in the plug-in or the copy in roll_checkpoints fails."""
    from tests import test_tabletop_hunt6 as H
    from tests.test_auto_H1_rerolls import WAKING
    from tests.test_lock9_critical_range import hold_sender, native

    real = H.sheet
    monkeypatch.setattr(H, "sheet", lambda *a, **kw: real(*a, **kw, primary="Resonance"))
    combat, table, mid = H.table_fight(tmp_path, [], ally_talents=[WAKING])

    def attack(engine):
        # "Rehearse Success: If the Test was made by you or an ally, reroll it."
        # The roll must have succeeded, so the attack is given an easy target.
        engine._add_modifier(engine.state.actors[H.RIGHT], "test:armor", "armor_class", "ADD", 100,
                             "SELF", expires_on="UNTIL_REMOVED")
        native(engine, 12, attacker=H.LEFT, target=H.RIGHT)

    H.on_hold(monkeypatch, attack)
    result = hold_sender(table, mid)()
    if result["status"] == "REACTION_REQUIRED":  # a manual ally is asked
        result = hold_sender(table, mid)([{**result["reaction"]["context"], "selection": "USE"}])
    assert result["status"] == "COMMITTED", result

    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.verify()["status"] == fresh.mechanical.replay()["status"] == "PASS"
    rewrites = [e for e in fresh.engine.events
                if e.event_type == "D20_REWRITTEN" and e.source_definition_id == WAKING]
    assert len(rewrites) == 1, "the ally's rewrite did not survive the commit"
    rewrite = rewrites[0]
    # The roller is Left; the user is Ally, and that is what the event records.
    assert rewrite.actor_id == H.LEFT
    assert rewrite.payload["user_id"] == H.ALLY
    assert set(rewrite.payload) == {"operation", "original", "result", "user_id"}

    # And the reloaded fight log names the user and the affected creature.
    feed_rows = table.events(mid, 0)["events"]
    line = next(row["summary"] for row in feed_rows
                if row["event_sequence"] == rewrite.sequence)
    assert line.startswith("Ally's Waking Dream Revision rerolled Left's attack roll"), line


# ------------------------------------------------------------------ finding 4

def test_a_bonus_naming_a_user_must_name_a_creature():
    """A producer may omit user_id, but may not send a non-id: the log would
    print a blank or nonsense owner. Same validation as the rewrite hook."""
    from combat import roll_checkpoints

    assert roll_checkpoints._optional_user_id({}) is None
    assert roll_checkpoints._optional_user_id({"user_id": None}) is None
    assert roll_checkpoints._optional_user_id({"user_id": "actor:me"}) == "actor:me"
    for bad in ("", 7, [], {}):
        with pytest.raises(ValueError, match="creature entity id"):
            roll_checkpoints._optional_user_id({"user_id": bad})


def test_a_bonus_naming_a_user_is_recorded_and_validated(monkeypatch):
    """End to end on the bonus hook: a supplied user reaches the event, and an
    invalid one raises ValueError. This does not assert transaction rollback."""
    from tests.h1_support import duel, ME
    from tests.test_lock_choices import install

    engine = duel([])
    install(monkeypatch, "d20_bonus",
            lambda *a: {"source_id": "test:bonus", "bonus": 1, "user_id": "actor:other"})
    before = len(engine.events)
    roll = engine._roll_save(engine.state.actors[ME], "DEX", 10, "test:bonus_probe")
    assert roll is not None
    bonuses = [e for e in engine.events[before:]
               if e.event_type == "D20_REWRITTEN" and e.payload.get("operation") == "bonus"]
    assert len(bonuses) == 1
    assert bonuses[0].payload["user_id"] == "actor:other"
    assert set(bonuses[0].payload) == {"operation", "bonus", "original", "result", "user_id"}

    install(monkeypatch, "d20_bonus",
            lambda *a: {"source_id": "test:bonus", "bonus": 1, "user_id": ""})
    with pytest.raises(ValueError, match="creature entity id"):
        engine._roll_save(engine.state.actors[ME], "DEX", 10, "test:bonus_probe_bad")
