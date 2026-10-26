"""Rule-level verdicts for the review's One Breath / Afterimage behaviour diffs.

Use only synthetic characters and real table commits. Reconstruct the service
before checking receipts, so no in-memory engine can satisfy persistence checks.
"""
import pytest

from combat import motion
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_a2r23_athletics_map import (
    BREATH, FIGHTER, FOE, ONE_BREATH, ROOT, engine_of, events, find,
    move_to, play, table_fight,
)
from tests.test_a2_athletics_table_reloads import route, setup


def cold(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    return TabletopService(combat, tmp_path), engine_of(combat, mid)


def test_activation_defers_attack_and_shared_strike_receipt_survives_new_service(tmp_path):
    _, table, mid = table_fight(tmp_path, [ONE_BREATH])
    table, engine = cold(tmp_path, mid)
    hp = engine.state.actors[FOE].current_hp
    attacks = len(events(engine, "ATTACK_ROLLED", FIGHTER))
    play(table, mid, find(table, mid, ONE_BREATH))
    table, engine = cold(tmp_path, mid)
    actor = engine.state.actors[FIGHTER]
    assert engine.state.actors[FOE].current_hp == hp
    assert len(events(engine, "ATTACK_ROLLED", FIGHTER)) == attacks
    assert actor.action_available
    assert actor.turn_flags["flight_typed_dashes"] == 2
    assert not actor.turn_flags.get("athletics_one_breath_strike")
    assert find(table, mid, "one_breath_strike", target=FOE)
    assert find(table, mid, "one_breath_unarmed", target=FOE)

    play(table, mid, find(table, mid, "one_breath_unarmed", target=FOE))
    table, engine = cold(tmp_path, mid)
    actor = engine.state.actors[FIGHTER]
    assert len(events(engine, "ATTACK_ROLLED", FIGHTER)) == attacks + 1
    assert actor.turn_flags["athletics_one_breath_strike"] == "1"
    assert actor.action_available, "the grant must not spend the ordinary Action"
    assert any(c.condition_id == BREATH for c in actor.conditions.values())
    for delivery in ("one_breath_strike", "one_breath_unarmed"):
        with pytest.raises(AssertionError):
            find(table, mid, delivery, target=FOE)


@pytest.mark.parametrize("image", [False, True])
def test_ignored_opportunities_do_not_spend_or_decline_enemy_reactions(tmp_path, image):
    talents = [ONE_BREATH] + (["TAL_ATHLETICS_AFTERIMAGE"] if image else [])
    # We explicitly end both turns below. Automatic seats expose only a
    # header, not a human end-turn button; keep both seats manual for this test.
    _, table, mid = table_fight(tmp_path, talents, bundle_transform=setup,
        control_modes={FIGHTER: "MANUAL", FOE: "MANUAL"})
    play(table, mid, find(table, mid, ONE_BREATH))
    table, before = cold(tmp_path, mid)
    hp = before.state.actors[FIGHTER].current_hp
    attack_count = len(events(before, "ATTACK_ROLLED", FOE))
    declined = len(events(before, "REACTION_DECLINED"))
    # Leave the adjacent foe's reach, return to it, and leave again.
    # No window should be opened even when the player would decline one.
    route(table, mid, [{"x": 3, "y": y} for y in range(4, 8)])
    table, engine = cold(tmp_path, mid)
    route(table, mid, [{"x": 3, "y": y} for y in range(7, 3, -1)])
    table, engine = cold(tmp_path, mid)
    route(table, mid, [{"x": 3, "y": y} for y in range(4, 8)])
    table, engine = cold(tmp_path, mid)
    actor, foe = engine.state.actors[FIGHTER], engine.state.actors[FOE]
    assert actor.current_hp == hp
    assert foe.reaction_available
    assert len(events(engine, "ATTACK_ROLLED", FOE)) == attack_count
    assert len(events(engine, "REACTION_DECLINED")) == declined
    assert not any(c.condition_id == "condition:typed.no_reactions_against"
                   for c in actor.conditions.values()), "only Opportunity Attacks are ignored"
    if image:
        assert motion.has_afterimage(actor)
        assert actor.turn_flags["athletics_afterimage_distance_ft"] == 45
        assert actor.turn_flags["athletics_afterimage_created"] == 1
        receipt = "athletics_one_breath_motion:TAL_ATHLETICS_AFTERIMAGE"
        assert type(actor.turn_flags[receipt]) is str
        play(table, mid, find(table, mid, "review.clear_afterimage"))
        table, engine = cold(tmp_path, mid)
        play(table, mid, move_to(table, mid, 3, 6))
        table, engine = cold(tmp_path, mid)
        assert not motion.has_afterimage(engine.state.actors[FIGHTER])
    # One Breath ends now; an unstruck image lasts through the enemy's turn,
    # and its threshold/receipt resets only at the owner's next turn.
    play(table, mid, table.state(mid)["menu"]["end_turn"])
    table, engine = cold(tmp_path, mid)
    assert not any(c.condition_id == BREATH
                   for c in engine.state.actors[FIGHTER].conditions.values())
    play(table, mid, table.state(mid)["menu"]["end_turn"])
    table, engine = cold(tmp_path, mid)
    actor = engine.state.actors[FIGHTER]
    assert not motion.has_afterimage(actor)
    assert not actor.turn_flags.get("athletics_one_breath_strike")
    assert not actor.turn_flags.get("athletics_afterimage_created")
