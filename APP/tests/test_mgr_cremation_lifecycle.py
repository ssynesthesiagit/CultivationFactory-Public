"""Review lifecycle regressions through native journey commits and cold reload."""
import ast
import json
from pathlib import Path

from tests import test_mgr_cremation_native as native
from tests.h1_support import ROOT


def test_advanced_rite_uses_current_capacity_and_qi_authority(tmp_path,monkeypatch):
    original_sheet=native.sheet
    def starting_sheet(*args,**kwargs):
        document=original_sheet(*args,**kwargs)
        document['identity']['proficiency_bonus']=2
        return document
    monkeypatch.setattr(native,'sheet',starting_sheet)
    cold,jid,world,act=native.game(tmp_path,monkeypatch,cl=3)

    def remains(scope,kind='cultivation_residue'):
        return {'id':'remains:'+scope,'kind':kind,'meaningful':1,
                'position':{'x':3,'y':4},'source_cl':3,'properties':{}}

    for scope in ('first','second'):
        world('remains',scope,remains(scope))
        state=act('cremation_rite',{'scope':scope,'result':'ash'})
    assert state['actors'][native.A]['source_states'][native.PARENT]['ash']==2
    acquired=state['actors'][native.A]['source_states'][native.PARENT]['sheet']
    finished=act('finish',{})
    assert cold().journey_state(jid)==finished

    # Advancement is the real owner's current source sheet; the retained
    # acquisition sheet deliberately stays at PB2 / Qi CL3 for provenance.
    document=cold()._factory_owner_sheet('cremator')
    document['identity'].update(proficiency_bonus=3,cultivation_level=8)
    document['path_and_subpath']['paths'][0].update(attainment=7,effective_cl=6)
    state=cold().create_journey(project_ids=['cremator','target'],arena_id='scene',
        positions={native.A:{'x':3,'y':3},native.B:{'x':6,'y':3}},
        base_paces={native.A:100,native.B:100})
    assert state['journey_id']!=jid
    jid=state['journey_id']
    row=next(row for row in state['actors'][native.A]['bundle']['typed_passives']
        if row.get('block')=='cremation_cinder_heart')
    assert row['numbers']['pb']==3 and row['numbers']['cl']==6

    def rite(scope,result,kind='cultivation_residue'):
        before=cold().journey_state(jid)
        declared=cold().journey_world_fact(jid,before['revision'],{
            'source':native.PARENT,'subject':native.A,'kind':'remains','scope':scope,
            'value':remains(scope,kind),'expires_at':2592000,'readers':[native.A]})
        after=cold().journey_act(jid,declared['revision'],native.A,'cremation_rite',
            {'scope':scope,'result':result})
        assert cold().journey_state(jid)==after
        return after

    for scope in ('third','at-current-capacity'):
        state=rite(scope,'ash')
        source=state['actors'][native.A]['source_states'][native.PARENT]
        assert source['ash']==3
        assert state['actors'][native.A]['resources'][native.ASH]==3
        assert source['rites'][-1]['source_cl']==6
        assert source['sheet']==acquired
    state=rite('ward','reanimation','corpse')
    source=state['actors'][native.A]['source_states'][native.PARENT]
    assert source['remains']['remains:ward']['ward_source_cl']==6
    assert source['rites'][-1]['source_cl']==6
    assert json.loads(source['sheet'])['identity']['proficiency_bonus']==2


def test_source_lifecycle_hooks_are_discoverable_in_central_contract():
    # This registry is the required discovery surface for extension authors.
    documentation=ast.get_docstring(ast.parse((Path(ROOT)/'combat/ext/__init__.py').read_text()))
    signatures=(
        'journey_source_sheet(sheet, session, actor_id)',
        'journey_acquisition(session, actor_id, source, payload, sheet)',
        'journey_acquired(session, actor_id, source, acquisition_id)',
        'technique_resolution_enabled(ctx)',
        'technique_resolved(ctx, receipt)',
        'possession_operation_allowed(engine, actor, holder, item, operation, source)',
        'observer_source_profile(engine, source, data)',
    )
    for signature in signatures:
        assert signature in documentation
