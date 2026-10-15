"""Assigned rows through native acquisition, table commits and cold replay."""
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT,sheet as raw_sheet
from tests.r1i_service_support import fixture,candidate,OWNER,FOE
from tests.test_r1i_round3 import resolve,reload
from combat.ext.beauty_adorn_base import SOURCE as ADORN,PRESENT,MEMORY,USED
from combat.ext.ink_base_actions import LIVING,LASH,SUPPLY


def sheet(mids,**kwargs):
    """Acquire source-bound base packages; bases are never learned talents."""
    from canonical_catalog import CanonicalCatalogAuthorityService
    doc=raw_sheet(mids,**kwargs)
    block=doc.get('spheres_and_talents')
    if block:
        catalog=CanonicalCatalogAuthorityService(ROOT)
        packages=[row for sphere in block['sphere_record_ids'] for row in catalog.get_sphere(sphere)['automatic_base_abilities']]
        block['automatic_sphere_component_record_ids']=[r['runtime_component_id'] for r in packages]
        automatic=set(block['automatic_sphere_component_record_ids'])
        block['learned_talent_record_ids']=[r for r in block['learned_talent_record_ids'] if r not in automatic]
        assert all(r['automatic_grant'] and not r['counts_as_talent_choice'] for r in packages)
    return doc


@pytest.fixture(autouse=True)
def source_acquisition(monkeypatch):
    import tests.r1i_service_support as support
    monkeypatch.setattr(support,'sheet',sheet)


def test_lash_declares_type_and_shape_before_roll_cold(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[LASH])
    resolve(combat,mid,send,candidate(table,mid,'Ink Lash',FOE),{'choice:needle.ink_lash_type':'slashing','choice:needle.ink_lash_shape':'painted fang'})
    e=reload(tmp_path,mid)
    declaration=next(x for x in e.events if x.payload.get('brush_shape')=='painted fang')
    attack=next(x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.sequence>declaration.sequence)
    assert declaration.sequence<attack.sequence
    assert any(c.condition_id==SUPPLY for c in e.state.actors[OWNER].conditions.values())
    assert not any(c.condition_id==SUPPLY for c in e.state.actors[FOE].conditions.values())


def test_adorn_one_scoped_check_and_scene_cold(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[ADORN])
    resolve(combat,mid,send,candidate(table,mid,'Adorn the Moment: Advantage on Check',OWNER),{})
    assert any(c.condition_id==PRESENT for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())
    resolve(combat,mid,send,candidate(table,mid,'Adorn: make a presentation check'),{
        'choice:needle.source_check':'Performance','choice:needle.source_check_purpose':'grace','choice:needle.source_check_subject':OWNER})
    e=reload(tmp_path,mid)
    checks=[x for x in e.events if x.event_type=='CHECK_ROLLED' and x.actor_id==OWNER]
    assert checks[-1].payload['actor']['mode']=='ADVANTAGE'
    assert any(c.condition_id==USED for c in e.state.actors[OWNER].conditions.values())
    assert not any(c.condition_id==PRESENT for c in e.state.actors[OWNER].conditions.values())


def test_adorn_memory_witness_cold(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[ADORN])
    resolve(combat,mid,send,candidate(table,mid,'Adorn the Moment: Visually Memorable',OWNER),{})
    e=reload(tmp_path,mid)
    assert any(c.condition_id==MEMORY and c.data['subject']==OWNER for c in e.state.actors[FOE].conditions.values())
    assert not any('check_mode' in c.data.get('rule',{}) for c in e.state.actors[OWNER].conditions.values())


def test_native_journey_actual_writing_expiry_permanence_wrong_owner(tmp_path,monkeypatch):
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:sheet([LIVING] if pid=='host' else [],cl=10,name=pid))
    arena={'stable_id':'battlefield:ink','display_name':'Writing room','width_squares':8,'height_squares':8,'square_size_ft':5,'terrain_regions':[],'starting_positions':{}}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self:{'room':arena})
    service=CombatService(ROOT,tmp_path);host='actor:factory.host';guest='actor:factory.guest'
    state=service.create_journey(project_ids=['host','guest'],arena_id='room',positions={host:{'x':2,'y':2},guest:{'x':3,'y':2}},base_paces={host:5,guest:5});jid=state['journey_id']
    def act(aid,kind,payload):
        s=CombatService(ROOT,tmp_path);before=s.journey_state(jid)
        return s.journey_act(jid,before['revision'],aid,kind,payload)
    payload={'origin':'brush','form':'map','content':'North gate -> river bridge','permanent':1,'surface':{'x':2,'y':2,'z':0}}
    act(host,'ink_write',payload)
    state=act(host,'ink_write',{**payload,'content':'Temporary route','permanent':0})
    assert len(state['actors'][host]['ink_writings'])==2
    with pytest.raises(ValueError):act(guest,'ink_write',payload)
    state=act(host,'wait',{'seconds':3600})
    assert CombatService(ROOT,tmp_path).journeys.replay(jid)['status']=='PASS'
    assert 'living_ink' not in state['actors'][host]
    assert [r['content'] for r in state['actors'][host]['ink_writings']]==[payload['content']]


@pytest.mark.parametrize('purpose',['other','grace'])
def test_adorn_qualifying_only_and_wrong_recipient(tmp_path,purpose):
    combat,table,mid,send,commit=fixture(tmp_path,[ADORN])
    resolve(combat,mid,send,candidate(table,mid,'Adorn the Moment: Advantage on Check',OWNER),{})
    assert not any('Adorn: make' in a['label'] for a in table.state(mid)['menu']['actions'] if a.get('actor_id')==FOE)
    resolve(combat,mid,send,candidate(table,mid,'Adorn: make a presentation check'),{
        'choice:needle.source_check':'Insight','choice:needle.source_check_purpose':purpose,'choice:needle.source_check_subject':OWNER})
    e=reload(tmp_path,mid);check=next(x for x in reversed(e.events) if x.event_type=='CHECK_ROLLED')
    assert check.payload['actor']['mode']==('ADVANTAGE' if purpose=='grace' else 'NORMAL')
    assert any(c.condition_id==PRESENT for c in e.state.actors[OWNER].conditions.values())==(purpose=='other')


@pytest.mark.parametrize('benefit',['motion','handling','check','space'])
def test_draw_native_paid_qi_then_listen_choose_whole_benefits(tmp_path,benefit):
    from combat.ext.thread_base_line import DRAW,LISTEN,LISTENING,line_rows
    from combat.observer_information import readings
    combat,table,mid,send,commit=fixture(tmp_path,[DRAW,LISTEN])
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    resolve(combat,mid,send,candidate(table,mid,'Draw the Line: Guide (Qi Thread)',FOE),{})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==before-1
    assert line_rows(e,e.state.actors[OWNER])
    resolve(combat,mid,send,candidate(table,mid,'Listen Through Tension'),{
        'choice:needle.thread_listen_line':FOE,'choice:needle.thread_listen_benefit':benefit})
    e=reload(tmp_path,mid)
    assert any(c.condition_id==LISTENING and c.data['benefit']==benefit for c in e.state.actors[OWNER].conditions.values())
    assert not readings(e,e.state.actors[FOE])
    if benefit=='check':
        # The check consumes only its own line-qualified single benefit.
        commit(table.state(mid)['menu']['end_turn']);owner_turn(table,mid,commit,OWNER)
        resolve(combat,mid,send,candidate(table,mid,'Listen: make a check involving the line'),{
            'choice:needle.source_check':'Perception','choice:needle.source_check_purpose':'line','choice:needle.source_check_subject':FOE})
        e=reload(tmp_path,mid)
        check=next(x for x in reversed(e.events) if x.event_type=='CHECK_ROLLED')
        assert check.payload['actor']['mode']=='ADVANTAGE'
        assert not any(c.condition_id==LISTENING for c in e.state.actors[OWNER].conditions.values())
    elif benefit in ('motion','handling'):
        private=readings(e,e.state.actors[OWNER]);assert private[-1]['details'][benefit]==('still' if benefit=='motion' else 'unknown')
    else:
        from combat.senses import pinpoints
        assert pinpoints(e,e.state.actors[OWNER],e.state.actors[FOE])


def test_jester_native_allied_foil_invitation_and_expiry(tmp_path):
    from combat.ext.jester import foil_mark
    from combat.typed_executor import bears_mark
    from combat.observer_information import readings
    combat,table,mid,send,commit=fixture(tmp_path,['JESTER_BASE_SET_THE_SCENE'],allies=[FOE])
    resolve(combat,mid,send,candidate(table,mid,'Set the Scene: Strike the Fool',FOE),{})
    e=reload(tmp_path,mid)
    assert bears_mark(e.state.actors[FOE],OWNER,foil_mark('Strike the Fool'))
    assert any('invitation' in r['details'] for r in readings(e,e.state.actors[FOE]))
    assert not readings(e,e.state.actors[OWNER])
    commit(table.state(mid)['menu']['end_turn']);owner_turn(table,mid,commit,OWNER)
    e=reload(tmp_path,mid)
    assert not bears_mark(e.state.actors[FOE],OWNER,foil_mark('Strike the Fool'))


def test_press_mark_actual_surface_persists_native(tmp_path):
    from combat.ext.ink_base_actions import PRESS,mark_endpoints
    combat,table,mid,send,commit=fixture(tmp_path,[PRESS])
    resolve(combat,mid,send,candidate(table,mid,'Press Mark: object or surface'),{'choice:needle.ink_surface':'$first'})
    e=reload(tmp_path,mid)
    endpoints=mark_endpoints(e,e.state.actors[OWNER])
    assert endpoints and endpoints[0]['position']==e.state.actors[OWNER].position
    assert not mark_endpoints(e,e.state.actors[FOE])
