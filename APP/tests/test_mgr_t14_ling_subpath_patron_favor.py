"""Source-backed compiled ownership -> table intents -> commits -> cold replay.

No fabricated compiled ownership/effect rows or direct provider execution is used
for behavioral evidence. Generic geometry guards are explicitly separate from
native delivery: Prayer has no area and cannot certify Widen or healing.
"""
import pytest

from tests import r1i_service_support as s
from tests.test_a2_qi_subpaths8 import fixture, cold

FAVOR = 'tianxia.subpath.qi.shugenja.feature.patron_spirit_s_favor'
PRAYER = 'tianxia.subpath.qi.shugenja.feature.elemental_prayer'
QI = 'resource:core.qi'
KEY = 'patron_spirit_favor'


def fight(tmp_path, *, patron='air', owned=True, cl=17, far=False, miss=False, extra=()):
    positions = {s.OWNER: {'x': 3, 'y': 6}, s.FOE: {'x': 9 if far else 5, 'y': 6},
                 s.SECOND: {'x': 12, 'y': 10}}
    return fixture(tmp_path, [PRAYER, *([FAVOR] if owned else []), *extra], patron=patron,
                   owner_cl=cl, owner_dc=50, foe_ac=200 if miss else 1,
                   positions=positions, wide=True, seed='MGR-T14-FAVOR-' + patron)


def options(table, mid, favor=None):
    label = 'Patron Spirit’s Favor: ' + favor if favor else 'Patron Spirit’s Favor:'
    return [o for g in table.state(mid)['menu']['actions'] if label in g['label'] for o in g['options']]


def use(table, mid, send, favor, *, recipient=None, consent='accept', roll='apply', water='push', target_id=s.FOE):
    cid = s.candidate(table, mid, 'Patron Spirit’s Favor: ' + favor, target_id)
    answers, prompts = [], []
    for _ in range(24):
        result = send(cid, answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        answer = {**prompt['context'], 'selection': 'DECLINE'}
        if prompt.get('choice'):
            source = prompt['context']['reaction_source_id']
            rows = prompt['choice']['options']
            want = ('apply' if roll == 'apply' else 'keep') if source.endswith('patron_favor_roll') else (
                recipient or s.OWNER) if source.endswith('patron_favor_shelter') else (
                consent if source == 'choice:willing.consent' else water if source.endswith('shugenja_water')
                else target_id if source.endswith('patron_favor_movement') else None)
            chosen = next((r for r in rows if r['id'] == want), rows[0])
            answer.update(selection='USE', option_ids=[chosen['id']])
        answers.append(answer)
    raise AssertionError('Favor did not commit')


def next_owner(table, mid, commit):
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != s.OWNER:
        commit(table.state(mid)['menu']['end_turn'])


@pytest.mark.parametrize('patron', ['air', 'fire'])
def test_empower_real_prayer_cost_damage_and_cold_replay(tmp_path, patron):
    combat, table, mid, send, commit = fight(tmp_path, patron=patron)
    before = cold(tmp_path, mid)
    assert before.state.actors[s.OWNER].resources[QI] == 30
    assert options(table, mid, 'Empower'), 'native Empower variant is missing'
    prompts = use(table, mid, send, 'Empower')
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[s.OWNER]
    assert actor.resources[QI] == 27
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.actor_id == s.OWNER and e.payload.get('resource_id') == QI]
    assert len(spends) == 1 and spends[0].payload['amount'] == 3
    assert actor.turn_flags[KEY] == f'{engine.state.round_number}:{s.OWNER}'
    bonuses = [r for r in engine.rolls if r.reason == 'PATRON_FAVOR_EMPOWER']
    assert len(bonuses) == 1 and bonuses[0].expression.startswith('3d8')
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED'][-1]
    assert damage.payload['modifier'] == 2 + bonuses[0].total
    assert damage.payload['total'] >= bonuses[0].total
    assert any(p['context']['reaction_source_id'].endswith('patron_favor_roll') for p in prompts)
    assert not options(table, mid)
    next_owner(table, mid, commit)
    assert options(table, mid, 'Empower')
    # The original technique remains reachable; declining a Favor uses only 1 Qi.
    base = next(o['candidate_id'] for g in table.state(mid)['menu']['actions']
                if 'Elemental Prayer' in g['label'] and 'Patron Spirit' not in g['label']
                for o in g['options'] if s.FOE in o.get('target_ids', []))
    commit(base)
    assert cold(tmp_path, mid).state.actors[s.OWNER].resources[QI] == 26


def test_empower_keep_is_not_a_retroactive_bonus(tmp_path):
    combat, table, mid, send, commit = fight(tmp_path, patron='fire')
    use(table, mid, send, 'Empower', roll='keep')
    engine = cold(tmp_path, mid)
    assert engine.state.actors[s.OWNER].resources[QI] == 27
    assert not any(r.reason == 'PATRON_FAVOR_EMPOWER' for r in engine.rolls)
    assert [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED'][-1].payload['modifier'] == 2


def test_overwhelm_is_subtracted_before_the_real_first_save(tmp_path):
    combat, table, mid, send, commit = fight(tmp_path, patron='fire')
    use(table, mid, send, 'Overwhelm')
    engine = cold(tmp_path, mid)
    penalties = [r for r in engine.rolls if r.reason == 'PATRON_FAVOR_OVERWHELM']
    assert len(penalties) == 1 and penalties[0].expression.startswith('1d4')
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1]
    assert save.payload['modifier'] == engine.state.actors[s.FOE].saving_throws['DEX'] - penalties[0].total
    assert engine.state.actors[s.OWNER].resources[QI] == 27
    assert engine.rolls.index(penalties[0]) < next(i for i,r in enumerate(engine.rolls) if r.roll_id == save.payload['roll_id'])


@pytest.mark.parametrize('patron,water,start,end', [('air','push',5,8), ('water','push',5,8), ('water','pull',9,6)])
def test_drive_one_native_push_or_pull_keeps_original_save_and_cost(tmp_path, patron, water, start, end):
    combat, table, mid, send, commit = fight(tmp_path, patron=patron, far=start==9)
    use(table, mid, send, 'Drive', water=water)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[s.FOE].position.x == end
    assert engine.state.actors[s.OWNER].resources[QI] == 27
    assert len([e for e in engine.events if e.event_type == ('SAVE_ROLLED' if patron=='water' else 'ATTACK_ROLLED')]) == 1


@pytest.mark.parametrize('consent,expected', [('accept',8), ('refuse',0)])
def test_shelter_requires_real_recipient_consent_on_another_players_turn(tmp_path, consent, expected):
    combat, table, mid, send, commit = fight(tmp_path, patron='fire', far=True)
    prompts = use(table, mid, send, 'Shelter', recipient=s.FOE, consent=consent)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[s.FOE].temporary_hp == expected
    assert engine.state.actors[s.OWNER].temporary_hp == 0
    assert engine.state.actors[s.OWNER].resources[QI] == 27
    consent_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:willing.consent')
    assert consent_prompt['context']['reactor_id'] == s.FOE
    offered = next(p for p in prompts if p['context']['reaction_source_id'].endswith('patron_favor_shelter'))
    assert s.FOE in {r['id'] for r in offered['choice']['options']}
    assert s.SECOND not in {r['id'] for r in offered['choice']['options']}
    assert 'Patron Spirit' in consent_prompt.get('moment', str(consent_prompt))


def test_shelter_near_origin_self_and_missed_distant_target_boundary(tmp_path):
    combat, table, mid, send, commit = fight(tmp_path, far=True, miss=True)
    prompts = use(table, mid, send, 'Shelter', recipient=s.OWNER)
    engine = cold(tmp_path, mid)
    offered = next(p for p in prompts if p['context']['reaction_source_id'].endswith('patron_favor_shelter'))
    assert {r['id'] for r in offered['choice']['options']} == {s.OWNER}
    assert engine.state.actors[s.OWNER].temporary_hp == 8
    assert engine.state.actors[s.FOE].temporary_hp == 0


@pytest.mark.parametrize('owned,cl', [(False,17), (True,9)])
def test_wrong_owner_and_below_cl10_have_no_favor(tmp_path, owned, cl):
    combat, table, mid, send, commit = fight(tmp_path, owned=owned, cl=cl)
    assert not options(table, mid)
    commit(s.candidate(table, mid, 'Elemental Prayer', s.FOE))
    engine = cold(tmp_path, mid)
    assert engine.state.actors[s.OWNER].resources[QI] == 29
    assert not any(r.reason.startswith('PATRON_FAVOR_') for r in engine.rolls)


@pytest.mark.parametrize('patron', ['air','metal','lightning'])
def test_no_save_favor_or_invented_movement_for_attack_patron(tmp_path, patron):
    combat, table, mid, send, commit = fight(tmp_path, patron=patron)
    assert not options(table, mid, 'Overwhelm')
    assert bool(options(table, mid, 'Drive')) == (patron == 'air')
    assert not options(table, mid, 'Widen')  # Prayer is expressly one creature.


@pytest.mark.parametrize('shape,extra', [('sphere',10), ('cylinder',10), ('cone',10), ('line',20), ('cube',10)])
def test_geometry_contract_guard_only_not_native_delivery(shape, extra):
    # Deliberately not counted as source acquisition or delivery evidence.
    from combat.ext.mgr_t14_patron_favor import widen
    row = {'parameters': {'typed': {'area': {'shape':shape,'size_ft':20,'width_ft':5}}}, 'radius_ft':20}
    assert widen(row)
    assert row['parameters']['typed']['area'] == {'shape':shape,'size_ft':20+extra,'width_ft':5}
    assert row['radius_ft'] == 20+extra


def test_no_elemental_tag_inference_guard_only():
    from combat.ext.mgr_t14_patron_favor import tagged
    assert not tagged({'qi_powered':True,'sphere':'tianxia.sphere.fire','damage_types':['fire']})
    assert not tagged({'qi_powered':False,'source_tags':['fire']})
    assert not tagged({'qi_powered':False, 'source':PRAYER, 'effects':[{'type':'shugenja_prayer'}]})
    assert not tagged({'source_tags':['fire']})
    assert tagged({'qi_powered':True,'source_tags':['fire']})


def test_real_fire_sphere_acquisition_does_not_invent_patron_tag(tmp_path):
    combat, table, mid, send, commit = fight(tmp_path, patron='fire', extra=('FIRE_BASE_CONFLAGRATION',))
    engine = cold(tmp_path, mid)
    fire = [a for a in engine.action_catalog.values()
            if a.owner_id == s.OWNER and (a.parameters.get('typed') or {}).get('sphere') == 'tianxia.sphere.fire']
    assert fire
    assert not any((a.parameters.get('typed') or {}).get(KEY) for a in fire)
    assert options(table, mid, 'Empower')


def test_patron_is_actual_owner_input_before_favor_admission(tmp_path):
    from tests.test_a2_qi_subpaths8 import choose
    from combat.ext.shugenja_prayer import patron
    saw = []
    def setup(combat, table, mid, send, commit):
        engine = cold(tmp_path, mid)
        assert patron(engine.state.actors[s.OWNER]) is None
        assert not options(table, mid)
        cid = s.candidate(table, mid, 'Finish fight setup')
        pending = send(cid)
        assert pending['status'] == 'REACTION_REQUIRED'
        assert pending['reaction']['context']['reaction_source_id'] == 'choice:needle.shugenja_patron'
        assert patron(cold(tmp_path, mid).state.actors[s.OWNER]) is None
        choose(send, cid, patron='water')
        saw.append(True)
    combat, table, mid, send, commit = s.fixture(tmp_path, [PRAYER,FAVOR], before_turns=setup)
    assert saw
    assert patron(cold(tmp_path, mid).state.actors[s.OWNER]) == 'water'
    assert options(table, mid, 'Overwhelm') and options(table, mid, 'Drive')


def test_automatic_empower_uses_native_roll_and_leaves_no_choice_scope(tmp_path):
    combat, table, mid, send, commit = fight(tmp_path, patron='fire')
    cid = s.candidate(table, mid, 'Patron Spirit’s Favor: Empower', s.FOE)
    s.force_ai_candidate(combat, mid, s.OWNER, cid)
    answers = []
    for _ in range(12):
        result = send(cid, answers, auto=True)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        answers.append({**p['context'], 'selection':'DECLINE'})
    else:
        raise AssertionError('automatic Favor did not commit')
    engine = cold(tmp_path, mid)
    assert len([r for r in engine.rolls if r.reason == 'PATRON_FAVOR_EMPOWER']) == 1
    assert engine.state.actors[s.OWNER].resources[QI] == 27


def public_fight(tmp_path, *, owned, patron):
    """Public saved-package acquisition; no supplied compiled bundles/rows."""
    import json
    import zipfile
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from combat.tabletop import ButtonStore
    from tests.h1_support import ROOT, sheet
    from tests.test_a2_qi_subpaths8 import choose
    pids = ['aaaaaaaa', 'ffffffff', 'dddddddd']
    ids = [FACTORY_ACTOR_PREFIX + pid for pid in pids]
    for i, pid in enumerate(pids):
        document = sheet([PRAYER, *([FAVOR] if owned else [])] if i == 0 else [], cl=17, dc=50)
        document['identity']['display_name'] = ['Invoker','Recipient','Bystander'][i]
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 500
        document['ability_scores_and_statistics']['technique_attack_bonus'] = 100
        document['ability_scores_and_statistics']['armor_class']['base_value'] = 1
        folder = tmp_path/'portable_characters'/pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(document))
        ButtonStore(tmp_path/'tabletop_buttons').save_reactions(pid, {'mode':'ask'}, set())
    combat = CombatService(ROOT,tmp_path)
    arena = combat.tabletop_maps.save({'display_name':'Favor source hall','width_squares':40,'height_squares':20,
        'walls':[],'terrain':[],'starts':{'team1':[[3,6]],'team2':[[5,6],[12,10]]}})
    mid = combat.create_factory_match(project_ids=[pids[0]],opponent_actor_ids=ids[1:],
        control_modes={aid:'MANUAL' for aid in ids},arena_id='battlefield:map.'+arena['map_id'],
        match_seed='MGR-T14-FAVOR-'+patron,maximum_rounds=10)['match_id']
    table = TabletopService(combat,tmp_path)
    def send(cid, answers=()):
        menu=table.state(mid)['menu']
        return table.act(mid,cid,menu['decision_id'],menu['state_version'],0,list(answers))
    def commit(cid):
        answers=[]
        for _ in range(16):
            result=send(cid,answers)
            if result['status']=='COMMITTED':
                return result
            assert result['status']=='REACTION_REQUIRED',result
            p=result['reaction'];a={**p['context'],'selection':'DECLINE'}
            if p.get('choice'):
                a.update(selection='USE',option_ids=[p['choice']['options'][0]['id']])
            answers.append(a)
        raise AssertionError('public acquisition intent did not commit')
    choose(send,s.candidate(table,mid,'Finish fight setup'),patron=patron)
    while table.state(mid)['menu']['actor_id'] != ids[0]:
        commit(table.state(mid)['menu']['end_turn'])
    return combat,table,mid,send,commit,ids


@pytest.mark.parametrize('owned',[False,True])
@pytest.mark.parametrize('favor,patron',[('Empower','air'),('Overwhelm','fire'),('Drive','air'),('Shelter','fire')])
def test_public_saved_source_acquisition_to_native_delivery(tmp_path, owned, favor, patron):
    combat,table,mid,send,commit,ids=public_fight(tmp_path,owned=owned,patron=patron)
    owner_id,foe_id,_=ids
    before=cold(tmp_path,mid)
    if not owned:
        assert not options(table,mid)
        commit(s.candidate(table,mid,'Elemental Prayer',foe_id))
        engine=cold(tmp_path,mid)
        assert engine.state.actors[owner_id].resources[QI]==29
        assert not any(r.reason.startswith('PATRON_FAVOR_') for r in engine.rolls)
        return
    assert options(table,mid,favor), 'public acquisition did not publish the Favor'
    use(table,mid,send,favor,target_id=foe_id,recipient=foe_id)
    engine=cold(tmp_path,mid)
    assert engine.state.actors[owner_id].resources[QI]==27
    if favor=='Empower':
        assert len([r for r in engine.rolls if r.reason=='PATRON_FAVOR_EMPOWER'])==1
    elif favor=='Overwhelm':
        penalty=next(r.total for r in engine.rolls if r.reason=='PATRON_FAVOR_OVERWHELM')
        save=next(e for e in engine.events if e.event_type=='SAVE_ROLLED')
        assert save.payload['modifier']==engine.state.actors[foe_id].saving_throws['DEX']-penalty
    elif favor=='Drive':
        assert engine.state.actors[foe_id].position.x==before.state.actors[foe_id].position.x+3
    elif favor=='Shelter':
        assert engine.state.actors[foe_id].temporary_hp==8
