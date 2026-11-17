"""Sovereign has one timed damage path and preserves off-turn movement consent.

Rider lane C16: Brutal Shove is the printed Strength (Athletics) contest (combat/ext/brute_shove.py), no longer an attack roll: its
damage is the Strength modifier (2d8 + Strength under Sovereign Weight Incarnation), with no critical hit; the shoved creatures resist
badly here (as foe_ac=0 made the attack hit); manual creatures are asked push-or-Prone and their resisting skill; and the "two hits of
one action" case is now Perpetual Motion's second shove (an attack count does not exist on a contest).
"""
import pytest

from combat.canonical import canonical_sha256
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import resolve, reload
from tests.test_c4_protection_review import inherited_prompt_loader

BR = "TAL_BRUTE_"
SOV = BR + "SOVEREIGN_WEIGHT_INCARNATION"
FOCUS = "resource:core.martial_focus"


PICKS = {"choice:needle.brutal_shove_result": "push", "choice:needle.brute_contest_skill": "Athletics"}


def prepare(*, hammer=False, clumsy=()):
    def transform(bundles):
        for bundle in bundles:
            if bundle["actor_id"] in clumsy:
                bundle["skills"] = {"Athletics": -50, "Acrobatics": -50}  # it loses the shove contest
                bundle.pop("bundle_sha256", None)
                bundle["bundle_sha256"] = canonical_sha256(bundle)
        owner = bundles[0]
        # Strength is a real Strength SCORE (16 -> +3), because that is what the engine reads for a new Brute packet.
        # The saving-throw modifier is deliberately a DIFFERENT number (+6), so any damage path that mistakes "your
        # Strength modifier" for the saving throw fails these assertions instead of agreeing with them by accident: a
        # score-based reading deals +3, a saving-throw reading deals +6. (Setting only saving_throws.STR, as this
        # fixture used to, made the two paths look interchangeable -- AUTO107r1's regression.)
        owner["actor_template"]["strength_score"] = 16
        owner["actor_template"]["saving_throws"]["STR"] = 6
        if hammer:
            # A bounded fixture resource regain, persisted through a real effect,
            # isolates collision damage from separate focus-recovery abilities.
            for action in owner["action_catalog"]:
                if action["parameters"].get("typed", {}).get("source") == SOV:
                    action["parameters"]["typed"]["effects"].append(
                        {"type": "gain_resource", "resource_id": FOCUS, "flat": 1, "applies_to": "self"})
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)
    return transform


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("ai_turn", [False, True])
@pytest.mark.parametrize("hammer", [False, True])
def test_sovereign_single_state_damage_and_collision_table(tmp_path, active, ai_turn, hammer):
    talents = ["BRUTE_BASE_BRUTAL_SHOVE", SOV, *([BR + "HAMMER"] if hammer else [])]
    combat, table, mid, send, commit = fixture(tmp_path, talents, foe_ac=0,
        seed="C4-SOVEREIGN", bundle_transform=prepare(hammer=hammer, clumsy=(FOE, SECOND)),
        positions={OWNER: {"x": 3, "y": 0}, FOE: {"x": 4, "y": 0},
                   SECOND: {"x": 5, "y": 0} if hammer else {"x": 2, "y": 5}})
    groups = table.state(mid)["menu"]["actions"]
    assert not any("Brutal Shove + Sovereign" in g["label"] for g in groups)
    if active:
        commit(candidate(table, mid, "Sovereign Weight Incarnation", OWNER))
    engine = reload(tmp_path, mid)
    assert not any(m.target_field == "damage" for m in engine.state.actors[OWNER].modifiers.values())
    start, roll_start = len(engine.events), len(engine.rolls)
    cid = candidate(table, mid, "Brutal Shove", FOE)
    if ai_turn:
        force_ai_candidate(combat, mid, OWNER, cid)
    before, prompts = resolve(combat, mid, send, cid, PICKS, auto=ai_turn)
    engine = reload(tmp_path, mid)
    events, rolls = engine.events[start:], engine.rolls[roll_start:]
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    contest = next(e for e in events if e.event_type == "CHECK_ROLLED" and FOE in e.target_ids)
    assert contest.payload["success"]
    shove_rolls = [r for r in rolls if r.reason.startswith("DAMAGE:") and "d8" in r.expression and r.modifier == 3]
    if active:
        (shove_roll,) = shove_rolls  # "Brutal Shove damage becomes 2d8 + Strength modifier" (no critical: a contest)
        assert len(shove_roll.dice) == 2
        shove = shove_roll.total
    else:
        assert not shove_rolls
        shove = 3  # "deal Bludgeoning damage equal to your Strength modifier, minimum 0"
    hammer_rolls = [r for r in rolls if r.reason == "HAMMER_IMPACT_COLLISION"]
    bonus_rolls = [r for r in rolls if r.reason.startswith("DAMAGE:") and "d8" in r.expression and r.modifier == 0]
    if hammer:
        assert len(hammer_rolls) == 1
        assert len(bonus_rolls) == (2 if active else 0)  # one per affected creature
    else:
        assert not hammer_rolls and not bonus_rolls
    # Single shove packet, plus the two distinct collision mechanisms, never
    # the old extra paid modifier or an additional after-hit shove packet.
    assert len(damage) == 1 + len(hammer_rolls) + (1 if active and hammer else 0)
    expected = shove + sum(r.total for r in hammer_rolls)
    if active and hammer:
        expected += bonus_rolls[0].total
    assert before["actors"][FOE]["current_hp"] - engine.state.actors[FOE].current_hp == expected


@pytest.mark.parametrize("allow_move", [False, True])
@pytest.mark.parametrize("ai_attacker", [False, True])
@pytest.mark.parametrize("ai_bearer", [False, True])
def test_sovereign_offturn_movement_consent_pause_answer_reload(tmp_path, allow_move, ai_attacker, ai_bearer):
    combat, table, mid, send, commit = fixture(tmp_path, [SOV],
        foe_talents=["BRUTE_BASE_BRUTAL_SHOVE"], foe_ac=0, owner_ac=0, seed="C4-SOVEREIGN", bundle_transform=prepare(clumsy=(OWNER,)),
        positions={OWNER: {"x": 4, "y": 0}, FOE: {"x": 3, "y": 0}, SECOND: {"x": 2, "y": 5}})
    commit(candidate(table, mid, "Sovereign Weight Incarnation", OWNER))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    if ai_bearer:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    cid = candidate(table, mid, "Brutal Shove", OWNER)
    if ai_attacker:
        force_ai_candidate(combat, mid, FOE, cid)
    before, prompts = resolve(combat, mid, send, cid,
        {"choice:needle.sovereign_move": "move" if allow_move else "stay", **PICKS}, auto=ai_attacker)
    consent = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.sovereign_move"]
    assert len(consent) == (0 if ai_bearer else 1)
    if consent:
        text = str(consent[0])
        assert all(name in text for name in ("Sovereign Weight Incarnation", "Brutal Shove", "Owner", "Foe"))
        assert {o["id"] for o in consent[0]["choice"]["options"]} == {"stay", "move"}
    engine = reload(tmp_path, mid)
    position = engine.state.actors[OWNER].position.model_dump(mode="json")
    assert (position != before["actors"][OWNER]["position"]) == (allow_move and not ai_bearer)
    assert engine.state.actors[OWNER].resources[FOCUS] == before["actors"][OWNER]["resources"][FOCUS]
    assert engine.state.actors[OWNER].reaction_available == before["actors"][OWNER]["reaction_available"]


def test_sovereign_collision_guard_allows_distinct_shoves_of_one_action(tmp_path):
    """Two shoves in one action (Perpetual Motion's additional shove) each collide once: the collision guards are per shove."""
    combat, table, mid, send, commit = fixture(tmp_path, [SOV, BR + "HAMMER", BR + "PERPETUAL_MOTION"], foe_ac=0,
        seed="C4-SOVEREIGN", bundle_transform=prepare(hammer=True, clumsy=(FOE, SECOND)),
        positions={OWNER: {"x": 3, "y": 0}, FOE: {"x": 4, "y": 0}, SECOND: {"x": 5, "y": 0}})
    commit(candidate(table, mid, "Sovereign Weight Incarnation", OWNER))
    start = len(reload(tmp_path, mid).events)
    before, prompts = resolve(combat, mid, send, candidate(table, mid, "Brutal Shove + Perpetual Motion", FOE), PICKS)
    engine = reload(tmp_path, mid)
    events = engine.events[start:]
    assert len([e for e in events if e.event_type == "CHECK_ROLLED" and FOE in e.target_ids]) == 2
    assert len([r for r in engine.rolls if r.reason == "HAMMER_IMPACT_COLLISION"]) == 2
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert len(damage) == 6  # each shove: shove damage, Hammer, Sovereign's Hammer bonus
    rolls = [e for e in events if e.event_type == "DAMAGE_ROLLED" and FOE in e.target_ids]
    # Hammer's native roll is recorded without DAMAGE_ROLLED; count it separately.
    expected = sum(e.payload["total"] for e in rolls) + sum(
        r.total for r in engine.rolls if r.reason == "HAMMER_IMPACT_COLLISION")
    assert before["actors"][FOE]["current_hp"] - engine.state.actors[FOE].current_hp == expected
