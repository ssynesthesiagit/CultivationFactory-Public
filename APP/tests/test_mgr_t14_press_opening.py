"""Press the Opening through real acquisition, table commits and cold replay."""
import pytest

from combat.ext import warleader as wl
from combat.typed_reactions import physical_melee_reach
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_auto21_weapons import kit, SPEAR, DAGGER, AXE, EXTRA_ATTACK
from tests.h1_support import ROOT

BASE = "WARLEADER_BASE_PRESS_THE_OPENING_STANDARD"
BOW = "tianxia.mortal.weapon.dan_gong"


def make(tmp_path, *, owner_weapon=DAGGER, ally_weapon=DAGGER,
         owner_at=(3, 6), ally_at=(3, 7), foe_at=(4, 6), owned=True,
         extra_foes=0, extra_attack=False):
    return fixture(
        tmp_path, [BASE] if owned else [], ask=False, seed="MGR-T14-PRESS",
        owner_kit=kit(owner_weapon), ally_kit=kit(ally_weapon),
        foe_kit=kit(DAGGER), extra_foes=extra_foes,
        owner_features=(EXTRA_ATTACK,) if extra_attack else (),
        positions={OWNER: dict(zip(("x", "y"), owner_at)),
                   ALLY: dict(zip(("x", "y"), ally_at)),
                   FOE: dict(zip(("x", "y"), foe_at))})


def use(c, t, m, name, target=None):
    return settle(t, m, candidate(c, m, name, target=target).candidate_id)


def attack(c, t, m, actor=OWNER, target=FOE):
    e = c._load_session(m).engine
    before = len(e.events)
    row = next(x for x in e.legal_candidates()
               if x.target_ids == (target,)
               and e.action_catalog.get(x.source_definition_id)
               and e.action_catalog[x.source_definition_id].display_name.endswith(" attack"))
    action = e.action_catalog[row.source_definition_id]
    settle(t, m, row.candidate_id)
    e = c._load_session(m).engine
    rolls = [x for x in e.events[before:]
             if x.event_type == "ATTACK_ROLLED" and x.actor_id == actor]
    assert rolls
    return rolls, action


def bonus(roll):
    return roll.payload["modifier"]


def test_spear_partner_reach_and_both_allies_receive_bonus_after_cold_reload(tmp_path):
    c, t, m = make(tmp_path, ally_weapon=SPEAR, ally_at=(3, 8))
    e = reload(tmp_path, m)
    assert physical_melee_reach(e, e.state.actors[ALLY]) == 10
    use(c, t, m, "Set the Standard")
    e = reload(tmp_path, m)
    standard = next(x for x in e.state.actors[OWNER].conditions.values() if x.condition_id == wl.CONDITION)
    assert standard.expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert not e.state.actors[OWNER].bonus_action_available
    rolls, action = attack(c, t, m)
    boosted = bonus(rolls[0])
    assert e.state.actors[OWNER].action_available
    assert reload(tmp_path, m).state.actors[OWNER].turn_flags[f"wl_press:{FOE}"] == 1
    turn(t, m, ALLY)
    rolls, _ = attack(c, t, m, ALLY)
    assert bonus(rolls[0]) == boosted  # same compiled stats; each ally gets +2
    # The Standard expires on its source's next turn.
    turn(t, m, OWNER)
    assert not any(x.condition_id == wl.CONDITION for x in reload(tmp_path, m).state.actors[OWNER].conditions.values())
    plain, _ = attack(c, t, m)
    assert boosted == bonus(plain[0]) + 2


@pytest.mark.parametrize("owner_weapon,owner_at,ally_at", [
    (BOW, (3, 3), (3, 6)),  # ranged attack range is not melee reach
    (DAGGER, (3, 6), (3, 8)),  # partner cannot reach the foe
    (DAGGER, (3, 6), (11, 6)),  # partner outside Command Range
])
def test_range_and_command_boundaries_do_not_grant_bonus(tmp_path, owner_weapon, owner_at, ally_at):
    c, t, m = make(tmp_path, owner_weapon=owner_weapon, owner_at=owner_at, ally_at=ally_at)
    use(c, t, m, "Set the Standard")
    rolls, _ = attack(c, t, m)
    active_modifier = bonus(rolls[0])
    reload(tmp_path, m)
    turn(t, m, OWNER)  # already its turn; end it explicitly, then cycle back
    settle(t, m, t.state(m)["menu"]["end_turn"])
    turn(t, m, OWNER)
    plain, _ = attack(c, t, m)
    assert active_modifier == bonus(plain[0])


def test_opportunity_attack_is_off_turn_and_does_not_consume_own_turn_bonus(tmp_path):
    c, t, m = make(tmp_path)
    use(c, t, m, "Set the Standard")
    turn(t, m, FOE)
    e = c._load_session(m).engine
    before = len(e.events)
    move = next(x for x in e.legal_candidates() if x.destination
                and (x.destination.x, x.destination.y) == (5, 6))
    settle(t, m, move.candidate_id)
    e = reload(tmp_path, m)
    rolls = [x for x in e.events[before:] if x.event_type == "ATTACK_ROLLED" and x.actor_id == OWNER]
    assert rolls, "A real Opportunity Attack must execute"
    assert not e.state.actors[OWNER].turn_flags.get(f"wl_press:{FOE}")
    off_turn = bonus(rolls[0])
    turn(t, m, OWNER)
    # Source expiry and ordinary movement back into reach happen natively.
    use(c, t, m, "Set the Standard")
    move = next(x for x in c._load_session(m).engine.legal_candidates()
                if x.destination and (x.destination.x, x.destination.y) == (4, 6))
    settle(t, m, move.candidate_id)
    # Partner remains at (3,7), ten feet from the foe: no second ally in reach.
    rolls, _ = attack(c, t, m)
    assert bonus(rolls[0]) == off_turn


def test_non_owner_cannot_set_standard(tmp_path):
    c, t, m = make(tmp_path, owned=False)
    e = reload(tmp_path, m)
    assert not any(a.display_name == "Set the Standard" for a in e.action_catalog.values()
                   if a.owner_id == OWNER)
    rolls, _ = attack(c, t, m)
    assert not reload(tmp_path, m).state.actors[OWNER].turn_flags.get(f"wl_press:{FOE}")


def test_two_attacks_only_first_receives_bonus_and_use_survives_reload(tmp_path):
    c, t, m = make(tmp_path, extra_attack=True)
    use(c, t, m, "Set the Standard")
    rolls, _ = attack(c, t, m)
    assert len(rolls) >= 2  # Extra Attack scales with the real character's level.
    assert all(bonus(rolls[0]) == bonus(roll) + 2 for roll in rolls[1:])
    assert reload(tmp_path, m).state.actors[OWNER].turn_flags[f"wl_press:{FOE}"] == 1


def test_ineligible_first_attack_stays_used_after_reload_and_move_into_reach(tmp_path):
    """A missed reach prerequisite consumes the first roll, including across saves."""
    c, t, m = fixture(
        tmp_path, [BASE], ask=False, seed="MGR-T14-PRESS-MOVE",
        owner_kit=kit(DAGGER), ally_kit=kit(AXE, DAGGER, "tianxia.mortal.weapon.duan_jian"), foe_kit=kit(DAGGER),
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8},
                   FOE: {"x": 4, "y": 6}})
    use(c, t, m, "Set the Standard")
    turn(t, m, ALLY)  # The ally retains its Bonus Action for the off-hand attack.
    # Inventory order initially readies the dagger and short sword. Exchange
    # the spare for the axe using the same free equipment actions as a player.
    use(c, t, m, "Stow Duan Jian (Short Sword) (frees 1 hand; no Action)")
    use(c, t, m, "Draw Fu (Short Axe) (uses 1 hand; no Action)")
    e = c._load_session(m).engine
    assert e._distance_actor_to_actor(e.state.actors[ALLY], e.state.actors[FOE]) > physical_melee_reach(e, e.state.actors[ALLY])
    thrown = candidate(c, m, "Fu (Short Axe) thrown", target=FOE)
    plain = e.action_catalog[thrown.source_definition_id].parameters["typed"]["numbers"]["attack_bonus"]
    before = len(e.events)
    settle(t, m, thrown.candidate_id)
    e = reload(tmp_path, m)
    first = next(x for x in e.events[before:] if x.event_type == "ATTACK_ROLLED" and x.actor_id == ALLY)
    first_use = e.state.actors[ALLY].turn_flags.get(f"wl_press:{FOE}")

    # Continue through fresh services, not the original session's cached engine.
    c = type(c)(ROOT, tmp_path)
    t = type(t)(c, tmp_path)
    move = next(x for x in c._load_session(m).engine.legal_candidates()
                if x.destination and (x.destination.x, x.destination.y) == (4, 7))
    settle(t, m, move.candidate_id)
    # Throwing leaves a free hand. Draw the carried spare through its ordinary
    # free item action to hold the two weapons required for the off-hand hit.
    e = c._load_session(m).engine
    draw = next(x for x in e.legal_candidates()
                if e.action_catalog.get(x.source_definition_id)
                and e.action_catalog[x.source_definition_id].display_name.startswith("Draw Duan Jian"))
    settle(t, m, draw.candidate_id)
    e = reload(tmp_path, m)
    assert e.state.current_actor_id == ALLY
    for aid in (OWNER, ALLY):
        assert e._distance_actor_to_actor(e.state.actors[aid], e.state.actors[FOE]) <= physical_melee_reach(e, e.state.actors[aid])
    assert any(x.condition_id == wl.CONDITION for x in e.state.actors[OWNER].conditions.values())
    assert e.state.actors[ALLY].bonus_action_available
    before = len(e.events)
    use(c, t, m, "Bi Shou (Dagger) off-hand attack", FOE)
    e = reload(tmp_path, m)
    second = next(x for x in e.events[before:] if x.event_type == "ATTACK_ROLLED" and x.actor_id == ALLY)
    assert bonus(first) == plain
    assert bonus(second) == plain, "Moving into reach cannot grant +2 to the second attack"
    assert first_use == 1, "The ineligible first attack must survive the cold reload"
    assert e.state.actors[ALLY].turn_flags[f"wl_press:{FOE}"] == 1
