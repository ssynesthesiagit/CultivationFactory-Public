"""Review regressions through committed table hits and cold fight reloads."""
import copy

import pytest

from combat.ext import beast_echo_marrow as marrow
from combat.gate2_runtime_models import Position
from tests.test_a2r03_fix_round import _add_companion, COMPANION, _add_scoped_test_attack
from tests.test_a2r11_foundations import (
    FIGHTER, SERVICE_FOE, SERVICE_ALLY, MARROW_BARE, ECHO,
    _marrow, _service_fight, _until, _candidate, _play, _engine,
)


def test_shipped_spirit_companions_source_generates_and_spends_at_table(tmp_path, monkeypatch):
    def prepare(bundles):
        _add_scoped_test_attack(bundles, FIGHTER, 'TAL_SPIRIT_COMPANIONS_BINDING_SEAL')
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                      ally=True, prepare=prepare)
    _until(table, mid, FIGHTER, answer='DECLINE')
    _play(table, mid, _candidate(table, mid, 'Body pressure', SERVICE_FOE))
    cold = _engine(combat, mid)
    assert cold.state.actors[FIGHTER].resources[ECHO] == 1
    _play(table, mid, table.state(mid)['menu']['end_turn'])
    _until(table, mid, FIGHTER, answer='DECLINE')
    hp = _engine(combat, mid).state.actors[SERVICE_FOE].current_hp
    _, prompts = _play(table, mid, _candidate(table, mid, 'Body pressure', SERVICE_FOE), answer='strike')
    cold = _engine(combat, mid)
    assert any('Pack-Marrow Strike' in str(p) for p in prompts)
    assert hp - cold.state.actors[SERVICE_FOE].current_hp == 7
    assert any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == FIGHTER
               and e.payload.get('resource_id') == ECHO for e in cold.events)


@pytest.mark.parametrize('distance_ft, bonus', [(30, 8), (35, 4)])
def test_bonded_strike_quote_payment_damage_and_reload(tmp_path, monkeypatch, distance_ft, bonus):
    # Seal a deterministic long-reach natural attack in the companion's stat block.
    # The placement fixture isolates owner/companion range from attack reach.
    def prepare(bundles):
        _add_companion(bundles)
        owner = next(b for b in bundles if b['actor_id'] == FIGHTER)
        ally = next(b for b in bundles if b['actor_id'] == SERVICE_ALLY)
        companion = owner['summons'][-1]
        action = copy.deepcopy(next(a for a in ally['action_catalog'] if a['display_name'] == 'Unarmed Strike'))
        action.update(source_definition_id='action:test.natural_companion_hit', owner_id=COMPANION,
                      display_name='Companion natural attack', range_ft=60)
        action['parameters']['typed']['source'] = 'natural:test_companion'
        companion['action_catalog'] = [action]
        companion['actor_template']['action_ids'] = [action['source_definition_id']]
        for resource in owner['actor_template']['resources']:
            if resource['resource_id'] == ECHO:
                resource['initial'] = 1

    from combat import summons
    monkeypatch.setattr(summons, '_free_square_near',
                        lambda *args, **kw: Position(x=3 + distance_ft // 5, y=5, z=0))
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                      ally=True, prepare=prepare)
    # Summons inherit their owner's controller; only primary fighters can be
    # assigned one directly. Verify the native inherited path before acting.
    companion_view = next(a for a in combat.get_match(mid)['state']['actors']
                          if a['entity_id'] == COMPANION)
    assert companion_view['control_mode'] == 'MANUAL'
    _until(table, mid, FIGHTER, answer='DECLINE')
    _play(table, mid, _candidate(table, mid, 'Unarmed Strike', SERVICE_FOE))
    prior = _engine(combat, mid)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == FIGHTER
               and SERVICE_FOE in e.target_ids for e in prior.events)
    assert prior.state.actors[FIGHTER].resources[ECHO] == 1
    _play(table, mid, table.state(mid)['menu']['end_turn'])
    _until(table, mid, COMPANION, answer='DECLINE')
    before = _engine(combat, mid)
    assert before._distance_actor_to_actor(before.state.actors[FIGHTER], before.state.actors[COMPANION]) == distance_ft
    assert before.state.actors[COMPANION] in marrow.companions(before, before.state.actors[FIGHTER])
    hp = before.state.actors[SERVICE_FOE].current_hp
    _, prompts = _play(table, mid, _candidate(table, mid, 'Companion natural attack', SERVICE_FOE), answer='strike')
    assert any('Pack-Marrow Strike' in str(p) and f'add {bonus} damage' in str(p) for p in prompts)
    cold = _engine(combat, mid)
    assert hp - cold.state.actors[SERVICE_FOE].current_hp == 3 + bonus
    assert cold.state.actors[FIGHTER].resources[ECHO] == 0
    spent = [e for e in cold.events if e.event_type == 'RESOURCE_SPENT' and e.actor_id == FIGHTER
             and e.payload.get('resource_id') == ECHO]
    assert len(spent) == 1
    damage = [e for e in cold.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == FIGHTER
              and SERVICE_FOE in e.target_ids]
    assert damage[-1].payload['hp_damage'] == bonus
