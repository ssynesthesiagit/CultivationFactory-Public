"""INTERCEPTMSG1: an intercepted attack reads as one plain sentence; its d2 is labelled by purpose; unrelated
"not automated" riders for that same strike are hidden from the feed (the journal keeps them)."""
from combat.history_feed import format_history_feed
from combat.tabletop import dice_rows
from tests.test_mgr_t14_afterimage_attacks import ATTACKER, OWNER, producer, setup  # noqa: F401 (autouse seed fixture)
from tests.hunt15_support import act, reload

STRIKE = "action:test.strike"
RIDER = "Deliver the Dose is not automated; the GM resolves it. Adds 1d4 fire."


def _ev(seq, event_type, payload, *, intent="i1", target_ids=("t",), actor="a"):
    return {"sequence": seq, "event_type": event_type, "actor_id": actor, "target_ids": list(target_ids),
            "source_definition_id": STRIKE, "trigger_or_intent_id": intent, "transaction_id": f"x{seq}",
            "payload": payload}


def _intercepted(text="Afterimage: rolled 1 on a d2 \u2014 Guo Yuan's Deliver the Dose hit Tabik Damu's afterimage instead (the image is gone)."):
    return _ev(2, "PASSIVE_TRIGGERED", {"kind": "attack_target_intercepted", "text": text, "attack_source_id": STRIKE,
        "intent_id": "i1", "recipient_object_id": "img", "source_id": "cond", "condition_instance_id": "c1",
        "original_target_id": "t"}, target_ids=("img",))


NAMES = {"a": "Guo Yuan", "t": "Tabik Damu"}
DEFS = {STRIKE: "Deliver the Dose"}


def _feed(events):
    return format_history_feed(events, [], pre_state=None, post_state={"actors": {}}, actor_names=NAMES, definition_names=DEFS)


def test_intercepted_strike_reads_as_one_sentence_without_ids():
    rows = _feed([_intercepted()])
    assert [r["summary"] for r in rows] == [
        "Afterimage: rolled 1 on a d2 \u2014 Guo Yuan's Deliver the Dose hit Tabik Damu's afterimage instead (the image is gone)."]
    assert not any(token in rows[0]["summary"] for token in ("actor:", "object:", "img", "cond"))


def test_not_automated_rider_is_hidden_only_for_the_intercepted_strike():
    rider = _ev(3, "GM_RIDER", {"rider": RIDER})
    control = _feed([rider])
    assert len(control) == 1 and control[0]["event_type"] == "GM_RIDER"  # the reminder shows when nothing intercepted
    assert not any(r["event_type"] == "GM_RIDER" for r in _feed([_intercepted(), rider]))
    other = _ev(3, "GM_RIDER", {"rider": RIDER}, intent="i2")
    assert any(r["event_type"] == "GM_RIDER" for r in _feed([_intercepted(), other]))


def test_afterimage_d2_roll_is_labelled_by_what_it_decides():
    roll = {"roll_id": "r1", "actor_id": "a", "reason": "AFTERIMAGE:" + STRIKE + ":1", "expression": "1d2",
            "dice": [1], "discarded": [], "modifier": 0, "total": 1, "natural_result": 1, "mode": "NORMAL"}
    (row,) = dice_rows([roll], NAMES, DEFS)
    assert row["label"] == "Guo Yuan \u00b7 Afterimage: which one do you hit?"
    assert "1d2" not in row["label"]


def _strike(tmp_path, seed):
    c, t, mid = setup(tmp_path, seed)
    start = len(reload(c, mid).events)
    assert act(t, mid, "Test strike", target_id=OWNER)["status"] == "COMMITTED"
    e = reload(c, mid)
    decision = next(v for v in e.events[start:] if v.payload.get("kind") == "afterimage_targeting")
    feed = [item for boundary in c.history(mid)["boundaries"] for item in boundary["feed"]]
    return e, decision.payload["result"], feed


def test_real_table_roll_one_names_attacker_ability_target_and_afterimage(tmp_path):
    for seed in ("image-1", "image-2", "image-3", "image-4"):
        e, result, feed = _strike(tmp_path / seed, seed)
        if result == 1:
            break
    else:
        raise AssertionError("no seed rolled 1")
    attacker, target = e.state.actors[ATTACKER].display_name, e.state.actors[OWNER].display_name
    lines = [i["summary"] for i in feed if "rolled 1" in i["summary"]]
    assert len(lines) == 1, lines
    line = lines[0]
    assert attacker in line and "Test strike" in line and target in line and "afterimage" in line.lower()
    assert "rolled 1" in line and ATTACKER not in line and OWNER not in line


def test_real_table_roll_two_targets_normally(tmp_path):
    for seed in ("image-1", "image-2", "image-3", "image-4"):
        e, result, feed = _strike(tmp_path / seed, seed)
        if result == 2:
            break
    else:
        raise AssertionError("no seed rolled 2")
    target = e.state.actors[OWNER].display_name
    lines = [i["summary"] for i in feed if "rolled 2" in i["summary"]]
    assert len(lines) == 1, lines
    assert "targets" in lines[0] and target in lines[0] and "normally" in lines[0]
    assert not any("instead" in i["summary"] for i in feed)
