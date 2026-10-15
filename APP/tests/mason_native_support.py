"""Mason table actions, cold state and mechanical replay regressions."""


import pytest


from combat.gate5_service import CombatService


from tests.h1_support import ROOT


from tests import r1i_service_support as s


BASE='tianxia.subpath.qi.mason_cultivator.feature.'


FEATURES=[BASE+k for k in ('raise_barrier','emergency_repairs','bridge_the_impossible','fortress_crew','raise_the_imperial_bastion')]


def cold(tmp_path,mid):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']=='PASS'
    assert session.mechanical.replay()['status']=='PASS'
    return session.engine


def fixture(tmp_path,features=FEATURES,cl=18,damage=None,scene_objects=None,probe=False,positions=None,maximum_rounds=10,second_features=(),scene_document=None,record_kinds=None):
    def setup(bundles):
        # GM-authored printed identity input, validated by native compilation.
        # Never assign a runtime creature kind or invent an acquisition receipt.
        if record_kinds:
            import json,zipfile
            from combat.factory_compiler import compile_character
            for bundle in bundles:
                aid=bundle['actor_id']
                if aid not in record_kinds:continue
                from combat.gate5_service import FACTORY_ACTOR_PREFIX
                path=tmp_path/'portable_characters'/aid.removeprefix(FACTORY_ACTOR_PREFIX)/'current.zip'
                with zipfile.ZipFile(path) as archive:doc=json.loads(archive.read('Tianxia_Owner_Character_Sheet_v1.json'))
                doc['identity']['creature_type']=record_kinds[aid]
                compiled=compile_character(doc,actor_id=aid)
                with zipfile.ZipFile(path,'w') as archive:archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
                bundle.clear();bundle.update(compiled)
        if damage is None and not probe:return
        from combat.canonical import canonical_sha256
        bundle=next(b for b in bundles if b['actor_id']==s.OWNER)
        action={'source_definition_id':'test:mason.native_damage','display_name':'Damage a structure',
            'owner_id':s.OWNER,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'OBJECT','range_ft':60,
            'parameters':{'typed':{'source':'test:mason.native_damage','numbers':{},'duration':{'kind':'instant'},
                'effects':[{'type':'object_damage','flat':damage,'damage_types':['force']}]}}}
        if damage is not None:
            bundle['action_catalog'].append(action);bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        if probe:
            for key,target,effects in [('prone','SELF',[{'type':'condition','condition':'prone','applies_to':'target'}]),
                    ('save','ANY_CREATURE',[{'type':'save','ability':'STR','dc':50,'on_fail':[{'type':'condition','condition':'prone','applies_to':'target'}],'on_success':[]}])]:
                a={'source_definition_id':'test:mason.native_'+key,'display_name':'Native '+key+' probe','owner_id':s.OWNER,
                    'economy':'ACTION','resolution_kind':'TYPED','target_kind':target,'range_ft':60,
                    'parameters':{'typed':{'source':'test:mason.native_'+key,'numbers':{},'duration':{'kind':'instant'},'effects':effects}}}
                bundle['action_catalog'].append(a);bundle['actor_template']['action_ids'].append(a['source_definition_id'])
        bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    combat,table,mid,send,old_commit=s.fixture(tmp_path,features,owner_cl=cl,wide=True,allies=(s.SECOND,),bundle_transform=setup,positions=positions,second_talents=second_features)
    if scene_objects is not None or maximum_rounds!=10 or scene_document is not None:
        engine=cold(tmp_path,mid)
        saved=combat.tabletop_maps.save({'display_name':'Mason source declarations','width_squares':40,'height_squares':20,
            'walls':[],'objects':scene_objects or [],'starts':{'team1':[[3,6]],'team2':[[4,6],[5,6]]},**(scene_document or {})})
        arena=combat.factory_arenas()['battlefield:map.'+saved['map_id']]
        ids=list(engine.state.actors)
        mid=combat._finish_factory_match(engine.typed_bundle_documents,ids,
            {aid:a.team_id for aid,a in engine.state.actors.items()},
            {aid:a.position.model_dump(mode='json') for aid,a in engine.state.actors.items()},arena,[s.OWNER],ids[1:],
            control_modes={aid:'MANUAL' for aid in ids},match_seed='MASON-DECLARATION',display_name='Mason native declaration',maximum_rounds=maximum_rounds)['match_id']
        def send(cid,answers=()):
            menu=table.state(mid)['menu']
            return table.act(mid,cid,menu['decision_id'],menu['state_version'],0,list(answers))
        while table.state(mid)['menu']['actor_id']!=s.OWNER:
            assert send(table.state(mid)['menu']['end_turn'])['status']=='COMMITTED'
    def commit(selection,*,picks=None,decline=()):
        from combat.placement_menu import CHOICE
        from combat.ext.needle import cell_id
        from combat.gate2_runtime_models import Position
        cid,spot=selection if isinstance(selection,tuple) else (selection,None)
        answers=[]
        for _ in range(128):
            result=send(cid,answers)
            if result['status']=='COMMITTED':return result
            assert result['status']=='REACTION_REQUIRED',result
            p=result['reaction'];answer={**p['context'],'selection':'DECLINE'}
            if p.get('choice'):
                preferred=p['choice'].get('preferred') or [p['choice']['options'][0]['id']]
                if p['context']['reaction_source_id']==CHOICE and spot is not None:
                    preferred=[cell_id(Position(x=spot[0],y=spot[1],z=spot[2] if len(spot)>2 else 0),include_altitude=True)]
                source=p['context']['reaction_source_id']
                if source in (picks or {}):
                    preferred=(picks or {})[source]
                    preferred=[preferred] if isinstance(preferred,str) else preferred
                if source not in decline:answer.update(selection='USE',option_ids=preferred[:1])
            answers.append(answer)
        raise AssertionError('too many prompts')
    return combat,table,mid,send,commit


def at(table,mid,label,x,y):
    return (next(o['candidate_id'] for g in table.state(mid)['menu']['actions'] if g['label']==label
        for o in g['options']), (x,y))


def next_owner(table,mid,commit):
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])


def works(engine):
    return [o for o in engine.state.objects.values() if (o.component or {}).get('mason') and not o.destroyed]


def journey_fixture(tmp_path,features=FEATURES):
    combat,table,mid,send,commit=fixture(tmp_path,features=features)
    engine=cold(tmp_path,mid)
    journey=combat.journeys.create(engine.typed_bundle_documents,engine.battlefield_document,
        {aid:a.position.model_dump(mode='json') for aid,a in engine.state.actors.items()},
        {aid:3000 for aid in engine.state.actors})
    return combat,journey


def journey_wall_payload():
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    return {'source':BASE+'raise_barrier','form':'Low Wall','sections':[{
        'position':{'x':6,'y':8},'form':'Low Wall','length_ft':10,'width_ft':1,'height_ft':3,'rotation':0,
        'material_source':'terrain:'+cell_id(Position(x=6,y=8)),'legal_load':''}]}


def commit_other_table(table,mid,cid):
    answers=[]
    for _ in range(64):
        menu=table.state(mid)['menu']
        result=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
        if result['status']=='COMMITTED':return result
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction'];answer={**prompt['context'],'selection':'DECLINE'}
        if prompt.get('choice'):
            answer.update(selection='USE',option_ids=(prompt['choice'].get('preferred') or [prompt['choice']['options'][0]['id']])[:1])
        answers.append(answer)
    raise AssertionError('too many native table choices')

