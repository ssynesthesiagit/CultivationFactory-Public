"""Selected optional Axes targets survive a real table commit and reload."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import test_riders_lane3 as L


@pytest.mark.parametrize('decline', [False,True])
def test_cleaving_arc_selected_second_target_table_commit_reload(tmp_path,decline):
    ids = [L.ME,L.H.FOE,'actor:factory.r3i-near','actor:factory.r3i-chosen']
    sheets = [L.H._sheet(L.H.AXES,[L.H.HEWING,'TAL_AXES_CLEAVING_ARC'],L.H.AXE_KIT)] + [
        L.H._sheet(None,[],L.H.AXE_KIT) for _ in ids[1:]]
    sheets[0]['ability_scores_and_statistics']['abilities'][0].update(score=70,modifier=30)
    for d,a in zip(sheets,ids):
        d['identity']['display_name'] = a.rsplit('.',1)[-1]
    bundles = [compile_character(d,actor_id=a,reaction_plan={'ask':True}) for d,a in zip(sheets,ids)]
    combat = CombatService(L.H.ROOT,tmp_path)
    table = TabletopService(combat,tmp_path)
    mid = combat._finish_factory_match(bundles,ids,{a:'team:a' if a == L.ME else 'team:b' for a in ids},
        {a:{'x':x,'y':y} for a,(x,y) in zip(ids,[(3,6),(4,6),(4,5),(3,5)])},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],[L.ME],ids[1:],
        control_modes={a:'MANUAL' for a in ids},match_seed='R3I-CLEAVE',
        display_name='R3i Cleave targets',maximum_rounds=5)['match_id']

    def act(cid,answers=()):
        m = table.state(mid)['menu']
        return table.act(mid,cid,m['decision_id'],m['state_version'],0,list(answers))

    for _ in ids:
        m = table.state(mid)['menu']
        if m['actor_id'] == L.ME:
            break
        assert act(m['end_turn'])['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    before = engine.state.model_dump(mode='json')
    c = next(c for c in engine.legal_candidates() if c.display_name == L.STRIKE+'Bite + Cleaving Arc' and L.H.FOE in c.target_ids)
    result = act(c.candidate_id)
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['context']['reaction_source_id'] == 'choice:needle.second_attack'
    assert {o['id'] for o in prompt['choice']['options']} == set(ids[2:])
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    answer = {**prompt['context'],'selection':'DECLINE' if decline else 'USE',
              'option_ids':[] if decline else [ids[-1]]}
    assert act(c.candidate_id,[answer])['status'] == 'COMMITTED'
    loaded = CombatService(L.H.ROOT,tmp_path)._load_session(mid)
    targets = [e.target_ids for e in loaded.engine.events if e.event_type == 'ATTACK_ROLLED']
    assert targets == [(L.H.FOE,)] + ([] if decline else [(ids[-1],)])
    assert loaded.engine.state.actors[ids[2]].current_hp == before['actors'][ids[2]]['current_hp']
    assert loaded.mechanical.replay()['status'] == 'PASS'
