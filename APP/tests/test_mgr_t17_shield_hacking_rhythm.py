"""Shield-Hacking Rhythm (MGR-T17-rw007): the Shield half is a real STR save and a paid Edge Momentum rider.

The printed talent is optional: on a qualifying hit the saber user may spend 1 Edge Momentum, the target makes a
Strength saving throw, and on a failure it loses the next shield, parry, guard, or temporary AC bonus it would apply
before the start of the user's next turn. The engine keeps each Armor Class modifier with its source, so the denial
takes the Shield Bonus or the next positive AC modifier, whichever the target is still applying.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from combat import armour, ext
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine

sys.path.insert(0, str(Path(__file__).resolve().parent))
t = importlib.import_module("test_review_sw-athletics")

ROOT = Path(__file__).resolve().parents[1]
ME = t.ME
TALENT = "tianxia.talent.sabers.shield_hacking_rhythm"
FORWARD = "tianxia.talent.sabers.forward_cut"
RHYTHM = "Forward Cut + Shield-Hacking Rhythm"
EDGE = "resource:named.edge_momentum"
CONDITION = "condition:typed.shield_hacking_rhythm"
DAO_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}}
SHIELD_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]}}


def _saber_bundle():
    """A Sabers fighter whose own technique save DC is 50, so the foe always fails the printed save."""
    sheet = t._sheet("tianxia.sphere.sabers", [FORWARD, TALENT], DAO_KIT, dc=50)
    # Leave Saber-Line Pressure out: its once-a-turn Edge Momentum gain would hide the rider's own spend.
    sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
    return compile_character(sheet, actor_id=ME)


def _foe_bundle(*, shield: bool):
    sheet = t._sheet("", (), SHIELD_KIT if shield else {"starting_kit": {"items": []}}, dc=16)
    if shield:
        sheet["proficiencies"] = {"armor": ["Shield"]}  # the starting-kit Shield is worn, so it earns its +2
    return compile_character(sheet, actor_id=AN)


def _fight(*, shield: bool, edge: int = 1):
    engine = Gate4ControllerEngine(
        ROOT, match_seed="MGR17-SHIELDHACK", typed_bundles=(_saber_bundle(), _foe_bundle(shield=shield)),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.resources[EDGE] = edge
    foe.armor_class = -50  # every attack roll hits; the Shield Bonus is read through the ac hook, not the d20
    return engine, me, foe


def _ready(engine):
    me = engine.state.actors[ME]
    engine.state.current_actor_id = ME
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    return me


def _names(engine):
    return [candidate.display_name for candidate in engine.legal_candidates()]


def _use(engine, name):
    candidate = next(candidate for candidate in engine.legal_candidates() if candidate.display_name == name)
    engine.execute_intent(ActionIntent(
        intent_id=f"intent:{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=ME,
        target_ids=candidate.target_ids or (AN,)))
    return candidate


def _hit_with(engine, name):
    """Run the action until it hits (a natural 1 can miss even against the forced AC); a miss pays nothing."""
    for _attempt in range(8):
        _ready(engine)
        before = len([e for e in engine.events if e.event_type == "ATTACK_ROLLED"])
        _use(engine, name)
        hit = next((e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == ME), None)
        if hit is not None:
            return hit
    raise AssertionError(f"{name} never hit")


def _ac_penalty(engine, foe):
    return sum(value for value in ext.run("ac", engine, foe) if isinstance(value, int))


def test_failed_save_denies_the_next_shield_bonus_then_it_returns():
    engine, me, foe = _fight(shield=True)
    assert armour.shield_bonus_earning(engine, foe) == 2
    assert _ac_penalty(engine, foe) == 0

    _hit_with(engine, RHYTHM)

    assert me.resources[EDGE] == 0
    save = next(event for event in reversed(engine.events) if event.event_type == "SAVE_ROLLED")
    assert save.payload["dc"] == 50
    assert save.payload["success"] is False
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
    assert _ac_penalty(engine, foe) == -2  # the next incoming attack sees the Shield Bonus taken away

    # The next attack against the foe uses the denial up, even when it is an ordinary attack.
    _hit_with(engine, "Forward Cut")
    assert not [held for held in foe.conditions.values() if held.condition_id == CONDITION]
    assert _ac_penalty(engine, foe) == 0
    assert armour.shield_bonus_earning(engine, foe) == 2  # the Shield itself is not destroyed


def test_declining_the_edge_momentum_spend_leaves_pool_and_shield_alone():
    engine, me, foe = _fight(shield=True, edge=0)
    assert RHYTHM not in _names(engine)  # the paid rider is not offered with no Edge Momentum to spend
    me.resources[EDGE] = 1
    assert RHYTHM in _names(engine)

    _hit_with(engine, "Forward Cut")  # the printed "may" is declined by using the ordinary attack

    assert me.resources[EDGE] == 1
    assert not foe.conditions
    assert _ac_penalty(engine, foe) == 0
    assert armour.shield_bonus_earning(engine, foe) == 2


def test_no_shield_target_is_not_offered_the_rider_and_is_unchanged():
    engine, me, foe = _fight(shield=False)
    assert armour.shield_bonus_earning(engine, foe) == 0
    assert RHYTHM not in _names(engine)

    _hit_with(engine, "Forward Cut")

    assert me.resources[EDGE] == 1
    assert not foe.conditions
    assert _ac_penalty(engine, foe) == 0


def _add_defence(engine, foe, value, *, source="tianxia.test.guard_stance"):
    """A per-source Armor Class ADD modifier on the foe: a parry, a guard stance, or a temporary AC bonus."""
    engine._add_modifier(foe, source, "armor_class", "ADD", value, "SELF", expires_on="START_OF_SELF_NEXT_TURN")


def test_failed_save_takes_a_parry_or_guard_bonus_then_it_returns():
    """The parry/guard/temporary-AC half is automated: a foe with no Shield loses its next such bonus."""
    engine, me, foe = _fight(shield=False)
    _add_defence(engine, foe, 2)
    assert armour.shield_bonus_earning(engine, foe) == 0
    assert _ac_penalty(engine, foe) == 0
    assert RHYTHM in _names(engine)  # a parry is a bonus the denial can take, so the paid rider is offered

    _hit_with(engine, RHYTHM)

    assert me.resources[EDGE] == 0
    save = next(event for event in reversed(engine.events) if event.event_type == "SAVE_ROLLED")
    assert save.payload["success"] is False
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
    assert _ac_penalty(engine, foe) == -2  # the next incoming attack loses the parry's +2

    _hit_with(engine, "Forward Cut")
    assert not [held for held in foe.conditions.values() if held.condition_id == CONDITION]
    assert _ac_penalty(engine, foe) == 0
    assert sum(m.value for m in foe.modifiers.values() if m.target_field == "armor_class") == 2  # the parry itself is kept


def test_consuming_attack_is_scored_against_the_denied_ac():
    """The attack that uses the denial rolls with the bonus taken away; the attack after it gets the bonus back."""
    engine, me, foe = _fight(shield=True)
    _hit_with(engine, RHYTHM)
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
    start = len([e for e in engine.events if e.event_type == "ATTACK_ROLLED"])
    _hit_with(engine, "Forward Cut")
    _hit_with(engine, "Forward Cut")
    rolls = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME][start:]
    consuming, following = rolls[0], rolls[-1]
    assert consuming.payload["cover_bonus"] == 0 and following.payload["cover_bonus"] == 0
    assert int(following.payload["target_ac"]) == int(foe.armor_class) + int(engine._ac_modifier(foe))
    assert int(following.payload["target_ac"]) - int(consuming.payload["target_ac"]) == 2


def test_penalty_only_target_is_not_offered_and_pool_is_unchanged():
    """A target with no defensive bonus at all (only an AC penalty) gives the variant nothing to take: no Edge spent."""
    engine, me, foe = _fight(shield=False)
    _add_defence(engine, foe, -2, source="tianxia.test.exposed")
    assert RHYTHM not in _names(engine)

    _hit_with(engine, "Forward Cut")

    assert me.resources[EDGE] == 1
    assert not foe.conditions
    assert _ac_penalty(engine, foe) == 0


def test_second_use_while_the_denial_is_held_is_not_offered_and_spends_nothing():
    """Finding 2: a creature already bearing the denial cannot take more, so the variant must not charge Edge for it."""
    engine, me, foe = _fight(shield=True, edge=2)
    _hit_with(engine, RHYTHM)
    assert me.resources[EDGE] == 1
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]

    _ready(engine)
    assert RHYTHM not in _names(engine)
    assert me.resources[EDGE] == 1


def test_private_workspace_report_is_not_committed_to_the_repository():
    """Review finding 1: a lane's private workspace report (local paths, queue receipts) must not live in the repo."""
    repo = Path(__file__).resolve().parents[2]
    assert not (repo / "fix" / "MGR-T17-rw007-shieldhack-1.report.md").exists()


# ------------------------------------------------------------- review F2R2 fixes

def _split_the_shield_wall(engine, foe):
    """Split the Shield Wall's denial (break_guard, shield, next attack by anyone): the foe loses its Shield AC to the next attack."""
    from combat.ext import guard_broken

    engine._apply_condition(foe, guard_broken.CONDITION, "system:test", ME, expires_on="UNTIL_REMOVED",
                            data={"shield": True, "cover": False, "next": True, "axe": False, "by": "anyone", "label": "test"})


def _attack_on(engine, foe):
    """The attack from ME against the foe is being resolved now (as guard_broken reads it from before_attack)."""
    from combat.ext import guard_broken

    engine.__dict__[guard_broken.CURRENT] = {"attacker": ME, "target": foe.entity_id, "ranged": False, "axe": False}


def test_shield_already_denied_by_split_the_shield_wall_is_not_taken_again():
    """Review B1: guard_broken and Shield-Hacking Rhythm both read the same +2 Shield Bonus. One attack loses it once (-2, not -4)."""
    engine, me, foe = _fight(shield=True)
    _split_the_shield_wall(engine, foe)
    engine._apply_condition(foe, CONDITION, "system:test", ME, expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "test"})
    _attack_on(engine, foe)
    assert _ac_penalty(engine, foe) == -2

    # That attack uses up Split the Shield Wall's denial only. Shield-Hacking Rhythm had nothing it could take on this attack
    # beyond the Shield Bonus already gone, so it is still held and takes the Shield Bonus on the next attack.
    ext.run("event", engine, "ATTACK_ROLLED", {"target_ids": (AN,), "actor_id": ME})
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
    assert _ac_penalty(engine, foe) == -2


def test_shield_denied_elsewhere_leaves_the_parry_for_shield_hacking():
    """With a parry also held, the attack loses the Shield Bonus once (guard_broken) and the parry once (the rider)."""
    engine, me, foe = _fight(shield=True)
    _add_defence(engine, foe, 2)
    _split_the_shield_wall(engine, foe)
    engine._apply_condition(foe, CONDITION, "system:test", ME, expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "test"})
    _attack_on(engine, foe)
    assert _ac_penalty(engine, foe) == -4


def test_unused_denial_expires_at_the_casters_next_turn():
    engine, me, foe = _fight(shield=True)
    _hit_with(engine, RHYTHM)
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
    engine._expire_typed_for_checkpoint("START_OF_TURN", ME)
    assert not foe.conditions
    assert _ac_penalty(engine, foe) == 0


def test_permanent_armor_class_bonus_is_never_denied():
    """A non-expiring AC bonus is not a parry, guard stance or temporary bonus: the rider is not offered and takes nothing."""
    engine, me, foe = _fight(shield=False)
    engine._add_modifier(foe, "tianxia.test.permanent_ward", "armor_class", "ADD", 2, "SELF", expires_on="UNTIL_REMOVED")
    assert RHYTHM not in _names(engine)
    assert me.resources[EDGE] == 1
