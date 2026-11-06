"""INTERCEPTMSG1: an intercepted attack reads as one plain sentence; its d2 is labelled by purpose; unrelated
"not automated" riders for that same strike are hidden from the feed (the journal keeps them).

Feed-level only: synthetic events, names and abilities, so nothing here comes from an owner save or the rules text.
The table walk-through (a real compiled character) lives in tests/test_intercept_msg_1_table.py, which the publish
gate keeps local because compiling a character reads the typed-mechanics authority.
"""
from combat.history_feed import format_history_feed
from combat.tabletop import dice_rows

STRIKE = "action:test.strike"
RIDER = "Test Strike is not automated; the GM resolves it. Adds 1d4 fire."
NAMES = {"a": "Aster Vale", "t": "Bram Holt"}
DEFS = {STRIKE: "Test Strike"}


def _ev(seq, event_type, payload, *, intent="i1", target_ids=("t",), actor="a"):
    return {"sequence": seq, "event_type": event_type, "actor_id": actor, "target_ids": list(target_ids),
            "source_definition_id": STRIKE, "trigger_or_intent_id": intent, "transaction_id": f"x{seq}",
            "payload": payload}


def _intercepted(text="Afterimage: rolled 1 on a d2 \u2014 Aster Vale's Test Strike hit Bram Holt's afterimage instead (the image is gone)."):
    return _ev(2, "PASSIVE_TRIGGERED", {"kind": "attack_target_intercepted", "text": text, "attack_source_id": STRIKE,
        "intent_id": "i1", "recipient_object_id": "img", "source_id": "cond", "condition_instance_id": "c1",
        "original_target_id": "t"}, target_ids=("img",))


def _feed(events):
    return format_history_feed(events, [], pre_state=None, post_state={"actors": {}}, actor_names=NAMES, definition_names=DEFS)


def test_intercepted_strike_reads_as_one_sentence_without_ids():
    rows = _feed([_intercepted()])
    assert [r["summary"] for r in rows] == [
        "Afterimage: rolled 1 on a d2 \u2014 Aster Vale's Test Strike hit Bram Holt's afterimage instead (the image is gone)."]
    assert not any(token in rows[0]["summary"] for token in ("actor:", "object:", "img", "cond"))


def test_not_automated_rider_is_hidden_only_for_the_intercepted_strike():
    rider = _ev(3, "GM_RIDER", {"rider": RIDER})
    control = _feed([rider])
    assert len(control) == 1 and control[0]["event_type"] == "GM_RIDER"  # the reminder shows when nothing intercepted
    assert not any(r["event_type"] == "GM_RIDER" for r in _feed([_intercepted(), rider]))
    other = _ev(3, "GM_RIDER", {"rider": RIDER}, intent="i2")
    assert any(r["event_type"] == "GM_RIDER" for r in _feed([_intercepted(), other]))


def test_afterimage_d2_roll_is_labelled_by_what_it_decides():
    roll = {"roll_id": "r1", "actor_id": "a", "reason": "TARGET_INTERCEPT:" + STRIKE + ":1", "expression": "1d2",
            "dice": [1], "discarded": [], "modifier": 0, "total": 1, "natural_result": 1, "mode": "NORMAL"}
    (row,) = dice_rows([roll], NAMES, DEFS)
    # Finding 3: the shared label is generic (no ability name); the provider's reason head names the purpose.
    assert row["label"] == "Aster Vale \u00b7 Which target do you hit?"
    assert "1d2" not in row["label"]


# --- INTERCEPTMSG1 review fixes -------------------------------------------------------------------------------

def _struck(seq=4, intent="i1"):
    return _ev(seq, "ATTACK_ROLLED", {"roll_id": "r9", "total": 15, "modified_total": 15}, intent=intent)


def test_not_automated_rider_stays_when_a_later_strike_of_the_same_use_hit_the_creature():
    # Finding 1: a three-strike use whose strike 1 hit the image but whose strike 2 rolled against the creature.
    rider = _ev(5, "GM_RIDER", {"rider": RIDER})
    rows = _feed([_intercepted(), _struck(4), rider])
    assert [r["event_type"] for r in rows if r["event_type"] == "GM_RIDER"] == ["GM_RIDER"], rows


def test_generic_receipt_without_its_own_sentence_gets_a_plain_line_and_no_breakdown_fallback():
    # Finding 3: a valid receipt with only the documented fields (no "text") must not fall to the generic fallback.
    receipt = _ev(2, "PASSIVE_TRIGGERED", {"kind": "attack_target_intercepted", "attack_source_id": STRIKE,
        "intent_id": "i1", "recipient_object_id": "img", "source_id": "cond", "condition_instance_id": "c1",
        "original_target_id": "actor:test.bram"}, target_ids=("img",))
    names = {**NAMES, "actor:test.bram": "Bram Holt"}
    (row,) = format_history_feed([receipt], [], pre_state=None, post_state={"actors": {}}, actor_names=names,
        definition_names=DEFS)
    assert row["summary"] == "Aster Vale's Test Strike struck a stand-in instead of Bram Holt; no attack was made against Bram Holt."
    assert "Detailed breakdown" not in row["summary"]


def test_shared_roll_labels_carry_no_ability_name():
    # Finding 3: shared presentation names only the generic purpose; Afterimage's wording lives in its provider.
    from combat import tabletop
    assert not any("afterimage" in key.lower() or "afterimage" in value.lower() for key, value in tabletop._ROLL_PURPOSES.items())
