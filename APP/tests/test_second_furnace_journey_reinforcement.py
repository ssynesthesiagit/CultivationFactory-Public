"""Focused native Journey regression for Demon Seed Overdraw's reinforcement."""

import pytest
from tests.test_second_furnace_native import game, OWNER, f


def test_journey_seed_overdraw_requires_and_saves_reinforcement_choice(tmp_path,monkeypatch):
    cold,jid,_,state=game(tmp_path,monkeypatch,cl=18,seed='journey-seed-reinforcement',initial_qi=8)
    offers=cold().journey_menu(jid,OWNER)['options']
    seed_rows=[row for row in offers if row['kind']=='furnace_engine' and row['payload'].get('payment')=='seed']
    assert seed_rows, {'journey_options':offers}
    seed=seed_rows[0]
    state=cold().journey_act(jid,state['revision'],OWNER,seed['kind'],seed['payload'])
    options=cold().journey_menu(jid,OWNER)['options']
    choices=[row for row in options if row['kind']=='furnace_seed_reinforcement'
             and row['payload']['benefit']=='temp_hp']
    assert choices, {'journey_options':options}
    choice=choices[0]
    assert '1 Devil Qi' in choice['label']
    assert 'Gain 4 Temporary Hit Points' in choice['label']
    with pytest.raises(ValueError,match='Seed-Fed Reinforcement'):
        cold().journey_act(jid,state['revision'],OWNER,'wait',{'seconds':1})
    state=cold().journey_act(jid,state['revision'],OWNER,choice['kind'],choice['payload'])
    assert state['actors'][OWNER]['encounter_snapshot']['temporary_hp']==4
    assert not state['actors'][OWNER]['source_states'][f.PARENT].get('seed_reinforcement_pending')
    assert any(event['kind']=='SEED_FED_REINFORCEMENT' and event['benefit']=='temp_hp' for event in state['events'])
