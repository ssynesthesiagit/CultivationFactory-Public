"""HUNT102 S1: a damage packet reduced to nothing must name what reduced it.

Zheng Jingxu's "Heaven-Mark Violet Gold Duan Cha +4 attack: Pin" on Du Daoyuan read
"dealt 0 piercing to Du Daoyuan (8 rolled, reduced from 8 to 0)" with nothing visible on
Du Daoyuan to explain it. The reduction was correct -- Stamina Guard is a Reaction that
subtracts "1d10 per Stamina spent" after Resistance resolves (see the printed text in
authority/typed_mechanics/rules_text.json) -- and the fight had already recorded it on its own
line, "Du Daoyuan resolved Stamina Guard; Damage reduced by 9". What was missing was the link:
the commit line reported the gap but never named its cause, so a packet that reached zero read
as unexplained. These tests drive the real table and assert the commit line names the cause.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.worker2_support import OWNER, FOE, candidate, fixture, reload  # noqa: E402
from tests.cw2_service_support import add_action, seal  # noqa: E402
from tests.test_r9i_karma_persistence import act, end_turn  # noqa: E402

STAMINA = "resource:core.stamina"
GUARD = "tianxia.path.body_refining.feature.stamina_guard"
GUARD_REACTION = "reaction:typed." + GUARD


def prepare(bundles):
    """Give the owner a Stamina pool (the Guard costs Stamina) and the foe one piercing attack."""
    if not any(r["resource_id"] == STAMINA for r in bundles[0]["actor_template"]["resources"]):
        bundles[0]["actor_template"]["resources"].append(
            {"resource_id": STAMINA, "initial": 60, "maximum": 60})
    bundles[2]["actor_template"]["maximum_hp"] = 500
    bundles[2]["actor_template"]["armor_class"] = 1
    add_action(bundles[2], "Piercing Jab",
               [{"type": "damage", "flat": 4, "applies_to": "target", "damage_types": ["piercing"]}])
    seal(bundles[0])
    seal(bundles[2])


def jab(tmp_path):
    """The owner, attacked for 4 piercing, spends Stamina Guard. Returns (engine, before, feed rows)."""
    combat, table, mid = fixture(tmp_path, [], owner_path="Body Refining",
                                 owner_features=[GUARD], bundle_transform=prepare)
    for _ in range(6):
        if table.state(mid)["menu"]["actor_id"] == FOE:
            break
        end_turn(table, mid)
    engine = reload(tmp_path, mid)
    before = len(engine.events)
    cid = candidate(combat, mid, "Piercing Jab", target=OWNER).candidate_id
    answers = []
    for _ in range(20):
        result = act(table, mid, cid, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        context = prompt["context"]
        options = (prompt.get("choice") or {}).get("options") or []
        if context.get("reaction_source_id") == GUARD_REACTION:
            # 4 damage against the largest printed spend (4 Stamina, 4d10, minimum 4) always
            # reaches exactly 0, so the packet under test is the reported shape.
            answers.append({**context, "selection": "USE", "option_ids": [options[-1]["id"]]})
        else:
            answers.append({**context, "selection": "USE" if options else "DECLINE",
                            **({"option_ids": [options[0]["id"]]} if options else {})})
    else:
        raise AssertionError("the Guard prompt never resolved")

    engine = reload(tmp_path, mid)
    rows = _feed(engine, engine.events[before:])
    return engine, rows


def _feed(engine, events):
    from combat.history_feed import format_history_feed

    names = {a.entity_id: a.display_name for a in engine.state.actors.values()}
    definitions = {e.source_definition_id: e.source_definition_id for e in engine.events if e.source_definition_id}
    definitions[GUARD] = "Stamina Guard"
    definitions[GUARD_REACTION] = "Stamina Guard"
    return format_history_feed([e.model_dump() for e in events], [], pre_state=None, post_state={},
                               actor_names=names, definition_names=definitions)


def commit_line(rows):
    return " ".join(r["summary"] for r in rows if "dealt" in r["summary"] and "piercing" in r["summary"])


# ------------------------------------------------------------------------------- the reported packet
def test_a_packet_reduced_to_zero_names_the_reaction_that_reduced_it(tmp_path):
    """The exact H102-05 shape: 4 rolled, Stamina Guard takes all of it, 0 lands.

    Before the fix this read "(4 rolled, reduced from 4 to 0)": the number was reported, the
    cause was not, and a reader had to infer it from the reaction line above.
    """
    engine, rows = jab(tmp_path)
    packets = [e.payload for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]
    assert packets and packets[-1]["reduced_to"] == 0 and packets[-1]["rolled_or_pending_damage"] == 4, (
        f"this test is about a packet reduced to nothing; got {packets[-1] if packets else None}")
    line = commit_line(rows)
    assert line, rows
    assert "dealt 0 piercing" in line, line
    assert "reduced from 4 to 0" in line, line
    assert "by Stamina Guard" in line, f"the commit line must name what reduced it, got: {line}"


def test_the_named_reduction_is_the_one_that_actually_happened(tmp_path):
    """The name is read off the recorded reaction, not assumed: the Stamina it spent is the
    reduction the commit line reports."""
    engine, rows = jab(tmp_path)
    spent = [e.payload["amount"] for e in engine.events
             if e.event_type == "RESOURCE_SPENT" and e.payload.get("resource_id") == STAMINA]
    assert spent and max(spent) == 4, spent
    reaction = [e.payload for e in engine.events if e.event_type == "REACTION_RESOLVED"][-1]
    assert reaction["pending_before"] == 4 and reaction["pending_after"] == 0, reaction
    assert "reduced from 4 to 0" in commit_line(rows), commit_line(rows)


# ------------------------------------------------------------------------------- the feed, directly
def _feed_for(*events):
    from combat.history_feed import format_history_feed

    names = {"a1": "Zheng Jingxu", "t2": "Du Daoyuan"}
    definitions = {"action:test.jab": "Piercing Jab", GUARD: "Stamina Guard",
                   "feature:test.other_guard": "Bone Armor"}
    rows = format_history_feed(list(events), [], pre_state=None, post_state={},
                               actor_names=names, definition_names=definitions)
    return " ".join(r["summary"] for r in rows)


def _commit(**over):
    """A packet that lost everything to a reduction, unless a test says otherwise."""
    payload = {"rolled_or_pending_damage": 9, "reduced_to": 0, "temporary_hp_absorbed": 0,
               "hp_damage": 0, "damage_type": "PIERCING", "remaining_hp": 113}
    payload.update(over)
    return {"event_type": "DAMAGE_COMMITTED", "actor_id": "a1", "target_ids": ["t2"],
            "source_definition_id": "action:test.jab", "payload": payload}


def _reduction(source, *, checkpoint="DAMAGE_APPLICATION", reduction=9):
    return {"event_type": "REACTION_RESOLVED", "actor_id": "t2", "target_ids": ["t2"],
            "source_definition_id": source,
            "payload": {"checkpoint": checkpoint, "reduction": reduction,
                        "pending_before": 9, "pending_after": 0}}


def test_two_reactions_are_both_named():
    line = _feed_for(_reduction(GUARD, reduction=5), _reduction("feature:test.other_guard"), _commit())
    assert "reduced from 9 to 0 by Stamina Guard and Bone Armor" in line, line


def test_a_repeated_reaction_is_named_once():
    line = _feed_for(_reduction(GUARD), _reduction(GUARD), _commit())
    assert line.count("by Stamina Guard") == 1, line


def test_a_reaction_that_reduced_nothing_is_not_named():
    """An answered reaction that took no points off changes nothing, so it names nothing."""
    line = _feed_for(_reduction(GUARD, reduction=0), _commit(rolled_or_pending_damage=9, reduced_to=9,
                                                            hp_damage=9))
    assert line.endswith("Piercing Jab dealt 9 piercing to Du Daoyuan; 113 HP remained."), line


def test_only_a_damage_application_may_be_named_as_the_cause():
    """REACTION_RESOLVED also carries attack-roll guards and saving-throw bonuses. Those change
    no damage packet and must never be printed as what reduced it."""
    for checkpoint in ("ATTACK_HIT_BEFORE_DAMAGE", "SAVE_RESULT_BEFORE_DECLARED"):
        line = _feed_for(_reduction(GUARD, checkpoint=checkpoint), _commit())
        assert "reduced from 9 to 0 by" not in line, f"{checkpoint}: {line}"


def test_a_later_packet_does_not_inherit_the_previous_cause():
    """The commit closes the packet: a reaction that answered the first hit is not repeated as
    the cause of the second hit, which the engine resolved with no reduction of its own."""
    first = _commit(reduced_to=0, hp_damage=0)
    second = _commit(reduced_to=9, hp_damage=9, remaining_hp=104)
    line = _feed_for(_reduction(GUARD), first, second)
    assert "reduced from 9 to 0 by Stamina Guard" in line, line
    assert line.count("by Stamina Guard") == 1, line
    assert "dealt 9 piercing to Du Daoyuan; 104 HP remained." in line, line


def test_a_packet_with_no_recorded_cause_still_reads_as_before():
    """Older saved fights recorded the gap but no reaction line beside it. They keep the plain
    wording instead of gaining a blank or a code."""
    line = _feed_for(_commit(reduced_to=0, hp_damage=0))
    assert "reduced from 9 to 0" in line, line
    assert " by " not in line, line