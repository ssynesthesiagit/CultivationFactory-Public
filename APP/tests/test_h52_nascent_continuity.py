"""Nascent Continuity through real Qi spending, table commits, and reload.

"At the beginning of your turn, before other recovery, if you have 0 Qi: regain Qi equal to your Proficiency Bonus.
Use this once per scene." The fight is the scene: after the first recovery, a fresh service (as after a server
restart) keeps driving the saved fight, Lingyue spends to 0 Qi again, and her next turn starts without a second
Continuity recovery.
"""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h52_turn_start_support import ROOT, engine_at, fight, next_action

QI = "resource:core.qi"
FLAG = "nascent_continuity_used_round_scene"


def _recoveries(engine, owner_id):
    return [event for event in engine.events if event.event_type == "RESOURCE_GAINED"
            and event.source_definition_id.endswith("feature.nascent_soul.continuity") and event.actor_id == owner_id]


def _drive_to_turn_after_zero(combat, table, match_id, owner_id, steps):
    """Spend Lingyue's Qi on real Qi actions until it reaches 0, then advance to her next turn start.

    Returns the engine at that turn start (her menu showing), or fails the test."""
    zero_turns = None

    def spend_qi(menu):
        engine = engine_at(combat, match_id)
        owner = engine.state.actors[owner_id]
        # Forms are fixed on the sheet (FD-7), never picked in the fight; a character with no recorded Form
        # gets no Stable turn-start recovery, so only Continuity can refill Qi here.
        if owner.resources.get(QI, 0) <= 0:
            return None
        choices = []
        for group in menu.get("actions", []):
            action = engine.action_catalog.get(group.get("source_definition_id"))
            if action is None:
                continue
            cost = sum(int(amount) for resource, amount in action.costs if resource == QI)
            if 0 < cost <= owner.resources.get(QI, 0):
                choices.extend((cost, option.get("candidate_id")) for option in group.get("options", []))
        return max(choices)[1] if choices else None

    for _ in range(steps):
        engine = engine_at(combat, match_id)
        owner = engine.state.actors[owner_id]
        if zero_turns is not None and table.state(match_id)["menu"].get("actor_id") == owner_id \
                and owner.turns_started > zero_turns:
            return engine
        before_qi = owner.resources.get(QI, 0)
        next_action(table, match_id, owner_id, spend_qi)
        after = engine_at(combat, match_id).state.actors[owner_id]
        if before_qi > 0 and after.resources.get(QI, 0) == 0:
            zero_turns = after.turns_started
    pytest.fail("real Qi actions did not reach zero and return to Lingyue's next turn")


def _zero_spends(engine, owner_id, after_sequence=0):
    return [event for event in engine.events if event.event_type == "RESOURCE_SPENT" and event.sequence > after_sequence
            and event.actor_id == owner_id and event.payload.get("resource_id") == QI and event.payload.get("remaining") == 0]


def test_nascent_continuity_recovers_after_real_qi_actions_and_reload(tmp_path):
    combat, table, match_id, owner_id = fight(tmp_path, "lingyue", qi=24)
    first = _drive_to_turn_after_zero(combat, table, match_id, owner_id, 1200)
    owner = first.state.actors[owner_id]
    assert owner.resources[QI] >= owner.proficiency_bonus
    assert owner.turn_flags.get(FLAG) == 1
    assert len(_recoveries(first, owner_id)) == 1 and _zero_spends(first, owner_id)
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert reloaded.mechanical.replay()["status"] == "PASS"
    assert reloaded.engine.state.model_dump(mode="json") == first.state.model_dump(mode="json")
    recovered_at = _recoveries(first, owner_id)[0].sequence

    # Once per scene: a fresh service on the same saved fight (as after a restart) keeps playing it; Lingyue
    # spends back down to 0 Qi and her next turn starts without a second Continuity recovery.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    assert engine_at(combat, match_id).state.actors[owner_id].turn_flags.get(FLAG) == 1
    second = _drive_to_turn_after_zero(combat, table, match_id, owner_id, 1200)
    owner = second.state.actors[owner_id]
    assert _zero_spends(second, owner_id, recovered_at), "Lingyue never spent back down to 0 Qi"
    assert owner.turns_started > first.state.actors[owner_id].turns_started
    assert owner.turn_flags.get(FLAG) == 1
    assert len(_recoveries(second, owner_id)) == 1, "Nascent Continuity recovered twice in one scene"
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert reloaded.mechanical.replay()["status"] == "PASS"
    assert reloaded.engine.state.model_dump(mode="json") == second.state.model_dump(mode="json")
    assert reloaded.engine.state.actors[owner_id].turn_flags.get(FLAG) == 1

def test_nascent_continuity_spent_in_a_fight_closes_the_grow_replacement(tmp_path):
    """F10RSC: Nascent Continuity used in the fight, committed, then a Grow Form replacement is refused.

    The CL15 replacement window closes "before using your CL15 Nascent Soul feature". The use happens in the
    fight, so the commit path must persist it on the sheet's growth record; Grow then reads only that record."""
    from tests.h52_turn_start_support import PEOPLE
    from combat.ext.qi_path import NASCENT_SOUL
    from combat.tabletop_service import TabletopError
    combat, table, match_id, owner_id = fight(tmp_path, "lingyue")
    _drive_to_turn_after_zero(combat, table, match_id, owner_id, 1200)
    project_id = PEOPLE["lingyue"]
    saved = table.buttons.get(project_id).get("advancement") or {}
    assert [row["feature_id"] for row in saved.get("feature_uses") or []] == [NASCENT_SOUL]
    with pytest.raises(TabletopError) as refused:
        table.set_build_choice(project_id, "golden_core", choice="reservoir", slot=1)
    assert refused.value.code == "TABLETOP_GOLDEN_CLOSED"
