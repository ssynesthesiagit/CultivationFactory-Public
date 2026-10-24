"""MGR-T17-sabers-parry-1 review finding 1: a bystander's protection is credited to the protected creature.

Guard-Cutting Parry (and every reaction that answers for an ally) answers the damage packet of the
creature it protects. Its REACTION_RESOLVED record names the reactor as ``actor_id`` and the attacker in
``target_ids``, with ``protects`` naming the protected creature. The history reader used to credit the
reactor and the attacker, so the bystander's own next, unrelated commit named the parry as its cause.
These tests read the feed directly, the same way ``tests/test_pierce_reduction_reason.py`` does.
"""

PARRY = "tianxia.talent.sabers.guard_cutting_parry"
ATTACKER, BYSTANDER, ALLY = "a1", "b1", "t2"


def _feed(*events):
    from combat.history_feed import format_history_feed

    names = {ATTACKER: "Zheng Jingxu", BYSTANDER: "Lu Bian", ALLY: "Du Daoyuan"}
    definitions = {"action:test.jab": "Piercing Jab", "action:test.swing": "Heavy Swing",
                   f"feature:{PARRY}": "Guard-Cutting Parry"}
    rows = format_history_feed(list(events), [], pre_state=None, post_state={},
                               actor_names=names, definition_names=definitions)
    return [row["summary"] for row in rows]


def _protection(protected=ALLY, reduction=5):
    """The record ``_offer_drop_to_zero_or_bloodied`` / bystander protection writes for the parry."""
    return {"event_type": "REACTION_RESOLVED", "actor_id": BYSTANDER, "target_ids": [ATTACKER],
            "source_definition_id": f"feature:{PARRY}",
            "payload": {"checkpoint": "DAMAGE_APPLICATION", "reduction": reduction, "pending_before": 9,
                        "pending_after": 9 - reduction, "protects": protected}}


def _commit(source, attacker, target, *, rolled=9, reduced_to=0, hp_damage=0, remaining=50):
    return {"event_type": "DAMAGE_COMMITTED", "actor_id": attacker, "target_ids": [target],
            "source_definition_id": source,
            "payload": {"rolled_or_pending_damage": rolled, "reduced_to": reduced_to, "temporary_hp_absorbed": 0,
                        "hp_damage": hp_damage, "damage_type": "PIERCING", "remaining_hp": remaining}}


def test_the_protected_ally_commit_names_the_parry_that_protected_it():
    lines = _feed(_protection(), _commit("action:test.jab", ATTACKER, ALLY))
    line = " ".join(lines)
    assert "Du Daoyuan" in line and "reduced from 9 to 0 by Guard-Cutting Parry" in line, lines


def test_the_bystander_is_not_credited_with_a_reduction_it_never_took():
    """The bystander's later, unrelated hit must not name the parry it never used for that packet."""
    later = _commit("action:test.swing", ATTACKER, BYSTANDER, rolled=9, reduced_to=0)
    line = " ".join(_feed(_protection(), _commit("action:test.jab", ATTACKER, ALLY), later))
    assert line.count("by Guard-Cutting Parry") == 1, line


def test_the_attacker_is_not_credited_with_the_reduction_either():
    """The attacker is only the target of the parry's record; a later packet that lands on the attacker
    must not name a parry that reduced someone else's packet."""
    later = _commit("action:test.swing", ALLY, ATTACKER, rolled=9, reduced_to=0)
    line = " ".join(_feed(_protection(), later))
    assert "by Guard-Cutting Parry" not in line, line
