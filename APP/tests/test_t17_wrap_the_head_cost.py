"""T17 / RIDERWIRE1: Wrap the Head, Return the Edge pays its printed 1 Edge Momentum.

Printed (authority/typed_mechanics/rules_text.json): "Action Type: Reaction / Trigger: A melee attack misses
you, or you reduce melee damage with Guard-Cutting Parry / Cost: 1 Edge Momentum / Make one saber attack
against the triggering creature. Hit: Deal normal damage and make the target Guard Pressured until the start
of your next turn."

The reviewed row (authority/typed_mechanics/reviewed_final.d/wenxue.json) now states that printed cost itself,
in the authority's own cost shape (a list of alternatives), so the reaction compiles payable-or-blocked on the
character's named Edge Momentum pool instead of idling as "cost not automated": at 0 it is unaffordable and
cannot commit, at 1 it commits and the pool goes 1 -> 0, and the attack, the Guard Pressured mark and its
until-start-of-your-next-turn duration are unchanged.
"""

import json
from pathlib import Path

from combat import typed_reactions
from combat.typed_executor import bears_mark
from tests import test_auto_wenxue as W

ROOT = Path(__file__).resolve().parents[1]
TALENT = "tianxia.talent.sabers.wrap_the_head_return_the_edge"
EDGE = "resource:named.edge_momentum"
MISS = {"attack_kind": "weapon", "range_ft": 5}
PRINTED_COST = [[{"resource": "text", "text": "1 Edge Momentum"}]]


def _row(bundle):
    return next(row for row in bundle["typed_reactions"] if row["feature_id"] == TALENT)


def _missed_attack(engine, me, foe):
    """The checkpoint typed_executor.block_attack calls on a resolved melee miss."""
    before = (len(engine.events), len(engine.rolls))
    typed_reactions.on_attack_missed(engine, foe, me, MISS)
    return engine.events[before[0]:], engine.rolls[before[1]:]


def _counterattack_roll(rolls):
    return [roll for roll in rolls if str(roll.reason).startswith(f"ATTACK:{TALENT}")]


def test_wrap_the_head_return_the_edge_charges_its_printed_edge_momentum():
    # The printed cost is the reviewed row's own data, and it survives into the built authority.
    reviewed = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/wenxue.json").read_text())
    assert reviewed["mechanics"][TALENT]["cost"] == PRINTED_COST
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    assert authority["mechanics"][TALENT]["cost"] == PRINTED_COST
    assert authority["mechanics"][TALENT]["activation"]["economy"] == "reaction"

    bundle = W._bundle([TALENT, "SABERS_BASE_SABER_LINE_METHOD"])

    # (a) The Sabers character compiles the printed pool at 0 -- payable once it has momentum, never
    #     "cost not automated" -- and the row charges one of it.
    pools = {row["resource_id"]: row for row in bundle["actor_template"]["resources"]}
    assert pools[EDGE]["initial"] == 0, "the pool starts empty"
    assert pools[EDGE]["maximum"] >= 1, "at 0 the reaction is blocked on the pool, it is not unpriced"
    assert not [note for note in bundle["diagnostics"]["notes"] if "cost not automated" in note]
    assert [
        row for row in bundle["diagnostics"]["skipped"]["reaction"] if row == TALENT or TALENT in str(row)
    ] == [], "the reaction is typed, not skipped"
    row = _row(bundle)
    assert row["costs"] == [{"resource_id": EDGE, "amount": 1}]
    assert row["free"] is False

    # (b) At 0 the reaction is unaffordable, so a melee miss neither rolls a counterattack nor spends anything.
    engine = W._engine(bundle)
    me, foe = engine.state.actors[W.ME], engine.state.actors[W.AN]
    assert me.resources[EDGE] == 0
    assert typed_reactions._generic_affordable(engine, me, row) is False
    hp_before = foe.current_hp
    event, rolls = _missed_attack(engine, me, foe)
    assert _counterattack_roll(rolls) == []
    assert [e.event_type for e in event if e.event_type == "RESOURCE_SPENT"] == []
    assert me.resources[EDGE] == 0
    assert foe.current_hp == hp_before
    assert not bears_mark(foe, W.ME, "Guard Pressured")

    # (c) At 1 it is affordable, so the same miss commits it and the pool goes 1 -> 0.
    engine = W._engine(bundle)
    me, foe = engine.state.actors[W.ME], engine.state.actors[W.AN]
    me.resources[EDGE] = 1
    assert typed_reactions._generic_affordable(engine, me, row) is True
    event, rolls = _missed_attack(engine, me, foe)
    assert _counterattack_roll(rolls), "the counterattack is offered and rolled once the cost is paid"
    spent = [e for e in event if e.event_type == "RESOURCE_SPENT"]
    assert len(spent) == 1
    assert spent[0].payload == {"resource_id": EDGE, "amount": 1, "remaining": 0}
    assert me.resources[EDGE] == 0
    assert me.reaction_available is False, "a costed reaction still spends the Reaction"
    assert [e for e in event if e.event_type == "REACTION_RESOLVED"]

    # (d) The hit is unchanged: normal damage, and Guard Pressured until the start of your next turn.
    attack = next(effect for effect in row["effects"] if effect["type"] == "attack")
    assert [effect["type"] for effect in attack["on_hit"]] == ["damage", "mark"]
    assert attack["on_hit"][0]["weapon_damage"] is True
    assert attack["on_hit"][1]["mark"] == "Guard Pressured"
    assert attack["on_hit"][1]["duration"] == {"kind": "until_start_of_your_next_turn"}

    engine = W._engine(bundle)
    me, foe = engine.state.actors[W.ME], engine.state.actors[W.AN]
    foe.armor_class = 0  # any counterattack that is not a natural 1 lands
    marked = None
    for _attempt in range(8):
        me.resources[EDGE] = 1
        me.reaction_available = True
        hp_before = foe.current_hp
        event, _rolls = _missed_attack(engine, me, foe)
        if foe.current_hp < hp_before:
            committed = [e for e in event if e.event_type == "DAMAGE_COMMITTED"]
            assert committed, "the counterattack's damage is committed"
            assert me.resources[EDGE] == 0
            marked = next((c for c in foe.conditions.values()
                           if c.condition_id == f"condition:typed.mark.guard_pressured.{W.ME}"), None)
            break
    assert marked is not None, "a landed counterattack leaves the target Guard Pressured"
    assert marked.expires_on == "START_OF_MARKER_NEXT_TURN", "until the start of your next turn"
    assert bears_mark(foe, W.ME, "Guard Pressured")
