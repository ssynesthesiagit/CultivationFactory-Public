"""Printed Demon Mark: 'once per turn when you damage it, add Proficiency Bonus to the damage'. Hidden Strike supplies separate dice."""
import hashlib
import pytest
from tests.hunt36_support import HIDDEN, VEIL, LEFT, RIGHT, act, fight, reload, send, turn, weapon

MARK = "TAL_DAEMONIC_CULTIVATION_DEMON_MARK"


def seed_for(critical):
    def die(seed, counter):
        return int.from_bytes(hashlib.sha256(seed.encode() + b"\0" + counter.to_bytes(16, "big")).digest(), "big") % 20 + 1
    for i in range(10000):
        seed = f"H36-MATRIX-melee-{critical}-{i}"
        if die(seed, 2) <= 8 and die(seed, 3) == (20 if critical else 19) and die(seed, 4) < 20:
            return seed
    raise AssertionError("no seed")


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("critical", [False, True])
def test_folded_demon_mark_does_not_change_hidden_strikes_separate_dice_or_label(tmp_path, ai, critical):
    combat, table, mid = fight(tmp_path, [HIDDEN, VEIL, MARK], seed=seed_for(critical))
    turn(combat, table, mid)
    act(combat, table, mid, "Demon Mark")
    act(combat, table, mid, "end")
    turn(combat, table, mid)
    menu = table.state(mid)["menu"]
    cid = next(o["candidate_id"] for g in menu["actions"] if g["label"] == "Smoke Veil" for o in g["options"] if o.get("destination") == {"x": 3, "y": 6})
    send(combat, table, mid, cid)
    send(combat, table, mid, weapon(combat, mid).candidate_id, ai=ai)
    engine = reload(combat, mid)
    hidden = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED" and e.payload.get("damage_label") == "Hidden Strike"]
    assert len(hidden) == 1 and hidden[0].payload["expression"] == ("4d6+0" if critical else "2d6+0")
    marked = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and MARK in e.source_definition_id]
    # The printed Mark adds PB to the primary damage; it does not own another packet.
    assert marked == []
    primary = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
               and e.actor_id == LEFT and not e.payload.get("damage_label")]
    action = engine.action_catalog[primary[-1].source_definition_id]
    base = int(action.parameters["typed"]["weapon"]["damage"].get("modifier") or 0)
    assert len(primary) == 1 and primary[0].payload["modifier"] == base + 4
    feed = combat.history(mid)["boundaries"][-1]["feed"]
    rows = [row for row in feed if row["event_type"] == "DAMAGE_COMMITTED" and MARK in row["source_definition_id"]]
    assert rows == [], "Demon Mark modifies the primary roll rather than creating a labelled packet"
    hidden_rows = [row for row in feed if row["event_type"] == "DAMAGE_ROLLED"
                   and "Hidden Strike" in row["summary"]]
    assert len(hidden_rows) == 1


def test_child_context_attribution_follows_action_boundary_but_keeps_critical():
    from combat.typed_executor import Context
    from tests.h1_support import duel, ME, FOE

    engine = duel([])
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    ctx = Context(engine, actor, action, None, {}, [target], target, critical_hit=True).with_source("passive:test.parent")
    assert ctx.on_hit_context(target).effect_source == ctx.effect_source
    other = action.model_copy(update={"source_definition_id": "action:test.child"})
    child = ctx.on_hit_context(target, action=other)
    assert child.effect_source is None and child.damage_metadata() == {}
    assert child.critical_hit and child.damage_source == other.source_definition_id
    explicit = ctx.on_hit_context(target, action=other, effect_source="passive:test.child")
    assert explicit.source == "passive:test.child"
    assert ctx.source == "passive:test.parent"
