"""Prop attacks keep printed damage/cost without borrowing a stowed bow.

The hidden-square regressions exposed that generic weapon-delivery inference
bound Stone-Skipping Strike to an inventory bow. Its printed attack throws a
suitable prop, including a held weapon; it does not shoot that bow.
"""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.test_hidden_targeting import LEFT, RIGHT, STRIKE, table_fight, turn


@pytest.mark.parametrize('weapons', [('jian', 'gun'), ('jian', 'gun', 'gong_jian')],
                         ids=['no-bow', 'stowed-bow'])
def test_prop_attack_commits_printed_damage_and_cost_then_reloads(tmp_path, monkeypatch, weapons):
    combat, table, mid = table_fight(tmp_path, left_weapons=weapons)
    turn(table, mid, LEFT)
    before = combat._load_session(mid).engine
    actor = before.state.actors[LEFT]
    qi = actor.resources['resource:core.qi']
    fixed_dice(monkeypatch, [19] * 60)
    commit(cast_sender(combat, table, mid, STRIKE, target=RIGHT))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    action = next(row for row in loaded.engine.action_catalog.values()
                  if row.owner_id == LEFT and row.display_name == STRIKE)
    assert not action.parameters['typed'].get('delivered_by')
    assert action.parameters['typed'].get('weapon') is None
    assert action.range_ft == 90
    assert action.parameters['typed']['range_ft'] == 30
    assert action.parameters['typed']['long_range_ft'] == 90
    attacks = [event for event in loaded.engine.events
               if event.event_type == 'ATTACK_ROLLED' and event.source_definition_id == action.source_definition_id]
    assert len(attacks) == 1 and attacks[0].payload['mode'] == 'DISADVANTAGE'
    damage = [event for event in loaded.engine.events
              if event.event_type == 'DAMAGE_ROLLED' and event.source_definition_id == action.source_definition_id]
    # CL10: the prop's own 3d6 + key modifier, rather than the bow's 1d8.
    assert damage and damage[-1].payload['expression'] == '3d6+2'
    assert loaded.engine.state.actors[LEFT].resources['resource:core.qi'] == qi - 1
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
