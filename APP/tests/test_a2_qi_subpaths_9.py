"""Shipped Qi Subpath effects via table commits, session execute_intent and cold replay."""
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests import r1i_service_support as s

DUST = 'tianxia.subpath.qi.dust_cultivator.feature.'


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


@pytest.mark.parametrize('cl,count',[(6,3),(11,4),(17,5)])
@pytest.mark.parametrize('mode,dc,condition', [('Choking Mode',50,'poisoned'), ('Choking Mode',1,None),
    ('Eroding Mode',50,'ac'), ('Eroding Mode',1,None)])
def test_choking_dust_modes_scale_and_half(monkeypatch,tmp_path,mode,dc,condition,cl,count):
    original=s.sheet
    def sheet(mids,**kwargs):
        return original(mids,**{**kwargs,'cl':cl})
    monkeypatch.setattr(s,'sheet',sheet)
    combat,table,mid,send,commit=s.fixture(tmp_path,[DUST+'choking_dust'],owner_dc=dc)
    before=cold(tmp_path,mid);qi=before.state.actors[s.OWNER].resources['resource:core.qi']
    if mode == 'Choking Mode' and dc == 50:
        # The public service compiler must see through this generic extension
        # effect wrapper for both AI scoring and failed-save composition.
        action=next(a for a in before.action_catalog.values() if a.owner_id==s.OWNER
                    and a.display_name=='Choking Dust: Choking Mode')
        assert action.parameters['expected_damage'] > 0
        from combat.factory_compiler import _attach
        effect_tree=action.parameters['typed']['effects']
        attached=_attach(effect_tree,[{'type':'condition','condition':'prone','applies_to':'target'}],'failed_save')
        nested=next(e for e in attached if e.get('type')=='dust_choking_save')['effects'][0]
        assert nested['on_fail'][-1]['condition']=='prone'
    commit(s.candidate(table,mid,'Choking Dust: '+mode,s.FOE))
    engine=cold(tmp_path,mid);target=engine.state.actors[s.FOE]
    damage=[e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and 'choking_dust' in e.source_definition_id]
    assert damage and len(damage[-1].payload['dice'])==count and damage[-1].payload['expression'].startswith(f'{count}d6')
    amount=damage[-1].payload['total']
    assert 500-target.current_hp== (amount if dc==50 else amount//2)
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==qi-2
    assert bool([c for c in target.conditions.values() if c.condition_id=='condition:typed.poisoned']) == (condition=='poisoned')
    assert sum(int(m.value) for m in target.modifiers.values() if m.target_field=='armor_class') == (-1 if condition=='ac' else 0)
    assert not any(e.event_type=='GM_RIDER' and 'choking_dust' in e.source_definition_id for e in engine.events)
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    engine=cold(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.poisoned' for c in engine.state.actors[s.FOE].conditions.values())
    assert not any(m.target_field=='armor_class' for m in engine.state.actors[s.FOE].modifiers.values())


@pytest.mark.parametrize('mode,kind,immune',[('Choking Mode','construct',True),('Eroding Mode','construct',False),('Eroding Mode','incorporeal undead',True)])
def test_dust_recipient_physiology(monkeypatch,tmp_path,mode,kind,immune):
    original=s.sheet;calls=[]
    def sheet(mids,**kwargs):
        doc=original(mids,**kwargs)
        if calls:doc['identity']['creature_type']=kind
        calls.append(1);return doc
    monkeypatch.setattr(s,'sheet',sheet)
    combat,table,mid,send,commit=s.fixture(tmp_path,[DUST+'choking_dust'])
    commit(s.candidate(table,mid,'Choking Dust: '+mode,s.FOE));engine=cold(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==s.FOE]
    assert bool(saves)==(not immune)
    assert (engine.state.actors[s.FOE].current_hp==500)==immune


def test_owned_dust_cloud_penalty_and_no_caster_movement(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[DUST+'choking_dust',DUST+'dust_cloud'],wide=True)
    initial=cold(tmp_path,mid).state.actors[s.OWNER].position
    s.place(table,mid,'Dust Cloud',{'x':4,'y':6});engine=cold(tmp_path,mid)
    assert engine.state.actors[s.OWNER].position==initial
    assert any(z.active and DUST+'dust_cloud' in z.source_definition_id for z in engine.state.zones.values())
    commit(s.candidate(table,mid,'Choking Dust: Choking Mode',s.FOE));engine=cold(tmp_path,mid)
    rolls=[e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and 'DUST_CLOUD_PENALTY' in str(e.payload.get('reason'))]
    assert len(rolls)==1
    save=next(e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==s.FOE)
    assert save.payload['dc']==50+rolls[0].payload['total']


def test_eroding_dust_different_casters_refresh_one_penalty(monkeypatch,tmp_path):
    original=s.sheet
    monkeypatch.setattr(s,'sheet',lambda mids,**kwargs:original(mids,**{**kwargs,'dc':50}))
    combat,table,mid,send,commit=s.fixture(tmp_path,[DUST+'choking_dust'],
        second_talents=(DUST+'choking_dust',),allies=(s.SECOND,),wide=True)
    commit(s.candidate(table,mid,'Choking Dust: Eroding Mode',s.FOE))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.SECOND:commit(table.state(mid)['menu']['end_turn'])
    commit(s.candidate(table,mid,'Choking Dust: Eroding Mode',s.FOE))
    engine=cold(tmp_path,mid)
    penalties=[m for m in engine.state.actors[s.FOE].modifiers.values() if m.target_field=='armor_class']
    assert len(penalties)==1 and penalties[0].value==-1 and penalties[0].source_actor_id==s.SECOND
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    assert sum(m.value for m in cold(tmp_path,mid).state.actors[s.FOE].modifiers.values() if m.target_field=='armor_class')==-1
    while table.state(mid)['menu']['actor_id']!=s.SECOND:commit(table.state(mid)['menu']['end_turn'])
    assert not any(m.target_field=='armor_class' for m in cold(tmp_path,mid).state.actors[s.FOE].modifiers.values())


@pytest.mark.parametrize('recipient',[s.OWNER,s.SECOND])
def test_choking_dust_manual_any_creature_ai_enemy_only(tmp_path,recipient):
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    combat,table,mid,send,commit=s.fixture(tmp_path,[DUST+'choking_dust'],allies=(s.SECOND,),wide=True)
    engine=cold(tmp_path,mid);actor=engine.state.actors[s.OWNER]
    candidates=engine.legal_candidates()
    dust=[c for c in candidates if 'choking_dust' in str(c.source_definition_id)]
    assert any(recipient in c.target_ids for c in dust)
    policy,_=PolicyLibrary(ROOT).for_actor(s.OWNER)
    ai=build_decision_context(engine,policy,for_ai=True)
    ai_dust=[c for c in ai.legal_candidates if 'choking_dust' in c.source_definition_id]
    assert ai_dust and all(s.FOE in c.target_ids for c in ai_dust)
    commit(s.candidate(table,mid,'Choking Dust: Choking Mode',recipient))
    assert cold(tmp_path,mid).state.actors[recipient].current_hp<500

MASON='tianxia.subpath.qi.mason_cultivator.feature.emergency_repairs'


def mason_fixture(monkeypatch,tmp_path,wall_damage=40):
    from combat.tabletop import normalize_map,to_battlefield
    from combat.canonical import canonical_sha256
    original=CombatService.factory_arenas
    def arenas(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        result['battlefield:factory_pillar_arena']=to_battlefield(normalize_map({
            'display_name':'Repair yard','width_squares':20,'height_squares':14,'walls':[],
            'objects':[{'id':1,'kind':'wall_section','x':4,'y':6,'hp':100,'ac':17,'threshold':0,'blocks':False}]}))
        return result
    monkeypatch.setattr(CombatService,'factory_arenas',arenas)
    def add(bundles):
        for b in bundles:
            action={'source_definition_id':'test:mason.damage.'+b['actor_id'],'display_name':'Chip the wall',
                'owner_id':b['actor_id'],'economy':'NONE','resolution_kind':'TYPED','target_kind':'OBJECT','range_ft':60,
                'parameters':{'free_primary':True,'typed':{'source':'test:mason.damage','numbers':{},'duration':{'kind':'instant'},
                    'effects':[{'type':'object_damage','flat':wall_damage,'damage_types':['force']}]}}}
            b['action_catalog'].append(action);b['actor_template']['action_ids'].append(action['source_definition_id'])
            probe={**action,'source_definition_id':'test:mason.brace.'+b['actor_id'], 'display_name':'Brace test','target_kind':'ANY_CREATURE',
                'parameters':{'free_primary':True,'typed':{'source':'test:mason.brace','numbers':{'save_dc':50},'duration':{'kind':'instant'},
                    'effects':[{'type':'save','applies_to':'target','ability':'str','on_fail':[{'type':'condition','condition':'prone','applies_to':'target'}]}]}}}
            b['action_catalog'].append(probe);b['actor_template']['action_ids'].append(probe['source_definition_id'])
            chip={**action,'source_definition_id':'test:mason.chip_creature.'+b['actor_id'],
                'display_name':'Chip a creature','target_kind':'ANY_CREATURE',
                'parameters':{'free_primary':True,'typed':{'source':'test:mason.chip_creature','numbers':{},'duration':{'kind':'instant'},
                    'effects':[{'type':'damage','applies_to':'target','flat':40,'damage_types':['force']}]}}}
            b['action_catalog'].append(chip);b['actor_template']['action_ids'].append(chip['source_definition_id'])
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    return s.fixture(tmp_path,[MASON],allies=(s.SECOND,),positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':3,'y':7},s.SECOND:{'x':4,'y':7}},bundle_transform=add,second_talents=(MASON,))


def test_emergency_repairs_object_and_reinforcement_reload_expiry(monkeypatch,tmp_path):
    combat,table,mid,send,commit=mason_fixture(monkeypatch,tmp_path)
    commit(s.candidate(table,mid,'Chip the wall'))
    before=cold(tmp_path,mid);obj=next(iter(before.state.objects.values()));oid=obj.object_id
    assert obj.current_hp==60
    qi=before.state.actors[s.OWNER].resources['resource:core.qi']
    commit(s.candidate(table,mid,'Emergency Repairs: Repair Structure',oid))
    engine=cold(tmp_path,mid);obj=engine.state.objects[oid]
    roll=next(e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and 'REPAIR:' in str(e.payload.get('reason')))
    assert obj.current_hp==min(100,60+roll.payload['total'])
    assert len(roll.payload['dice'])==3 and roll.payload['expression']=='3d8+2' and roll.payload['modifier']==2
    commit(s.candidate(table,mid,'Emergency Repairs: Reinforce Position',oid))
    engine=cold(tmp_path,mid);obj=engine.state.objects[oid]
    assert obj.ac==19 and obj.damage_threshold==4
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==qi-3
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    obj=cold(tmp_path,mid).state.objects[oid]
    assert obj.ac==17 and obj.damage_threshold==0
    assert 'mason_reinforcement' not in obj.component


def test_emergency_repairs_caps_nearly_full_object_after_reload(monkeypatch,tmp_path):
    combat,table,mid,send,commit=mason_fixture(monkeypatch,tmp_path,wall_damage=1)
    commit(s.candidate(table,mid,'Chip the wall'))
    engine=cold(tmp_path,mid);obj=next(iter(engine.state.objects.values()));oid=obj.object_id
    assert obj.current_hp==99
    commit(s.candidate(table,mid,'Emergency Repairs: Repair Structure',oid))
    engine=cold(tmp_path,mid);obj=engine.state.objects[oid]
    roll=next(e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and 'REPAIR:' in str(e.payload.get('reason')))
    assert roll.payload['total']>1 and obj.current_hp==100


def test_reinforcement_refresh_does_not_stack(monkeypatch,tmp_path):
    combat,table,mid,send,commit=mason_fixture(monkeypatch,tmp_path)
    engine=cold(tmp_path,mid);oid=next(iter(engine.state.objects))
    commit(s.candidate(table,mid,'Emergency Repairs: Reinforce Position',oid))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.SECOND:commit(table.state(mid)['menu']['end_turn'])
    commit(s.candidate(table,mid,'Emergency Repairs: Reinforce Position',oid))
    obj=cold(tmp_path,mid).state.objects[oid]
    assert (obj.ac,obj.damage_threshold)==(19,4)
    assert obj.component['mason_reinforcement']['owner']==s.SECOND
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    obj=cold(tmp_path,mid).state.objects[oid]
    assert (obj.ac,obj.damage_threshold)==(19,4)  # replaced caster's expiry cannot erase this caster's reinforcement
    while table.state(mid)['menu']['actor_id']!=s.SECOND:commit(table.state(mid)['menu']['end_turn'])
    obj=cold(tmp_path,mid).state.objects[oid]
    assert (obj.ac,obj.damage_threshold)==(17,0)


@pytest.mark.parametrize('recipient,mode',[(s.SECOND,'ADVANTAGE'),(s.FOE,'NORMAL')])
def test_reinforcement_adjacent_recipient_side(monkeypatch,tmp_path,recipient,mode):
    combat,table,mid,send,commit=mason_fixture(monkeypatch,tmp_path)
    oid=next(iter(cold(tmp_path,mid).state.objects))
    commit(s.candidate(table,mid,'Emergency Repairs: Reinforce Position',oid))
    commit(s.candidate(table,mid,'Brace test',recipient))
    engine=cold(tmp_path,mid)
    save=next(e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==recipient)
    assert save.payload['mode']==mode


def test_reinforcement_uses_current_relation_overrides_after_reload(monkeypatch,tmp_path):
    from combat.relations import ALLY, ENEMY
    combat,table,mid,send,commit=mason_fixture(monkeypatch,tmp_path)
    session=combat._load_session(mid)
    combat.change_relations(mid,change={'kind':'ACTOR_RELATION','subject':s.OWNER,'other':s.SECOND,'relation':ENEMY},
        expected_state_version=session.engine.state.state_version)
    session=combat._load_session(mid)
    combat.change_relations(mid,change={'kind':'ACTOR_RELATION','subject':s.OWNER,'other':s.FOE,'relation':ALLY},
        expected_state_version=session.engine.state.state_version)
    oid=next(iter(cold(tmp_path,mid).state.objects))
    commit(s.candidate(table,mid,'Emergency Repairs: Reinforce Position',oid))
    for recipient,expected in ((s.SECOND,'NORMAL'),(s.FOE,'ADVANTAGE')):
        commit(s.candidate(table,mid,'Brace test',recipient))
        engine=cold(tmp_path,mid)
        save=next(e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==recipient)
        assert save.payload['mode']==expected


def test_repair_construct_uses_relations_and_allows_neutral_construct(monkeypatch,tmp_path):
    from combat.relations import ALLY, ENEMY, NEUTRAL
    original=s.sheet
    def sheet(mids,**kwargs):
        doc=original(mids,**kwargs)
        doc['identity']['creature_type']='construct'
        return doc
    monkeypatch.setattr(s,'sheet',sheet)
    combat,table,mid,send,commit=mason_fixture(monkeypatch,tmp_path)
    commit(s.candidate(table,mid,'Chip a creature',s.SECOND))
    commit(s.candidate(table,mid,'Chip a creature',s.FOE))
    while table.state(mid)['menu']['actor_id']!=s.OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    session=combat._load_session(mid)
    combat.change_relations(mid,change={'kind':'ACTOR_RELATION','subject':s.OWNER,'other':s.SECOND,'relation':ENEMY},
        expected_state_version=session.engine.state.state_version)
    assert not any(s.SECOND in o.get('target_ids',[]) for g in table.state(mid)['menu']['actions']
        if g['label']=='Emergency Repairs: Repair Construct' for o in g['options'])
    session=combat._load_session(mid)
    combat.change_relations(mid,change={'kind':'ACTOR_RELATION','subject':s.OWNER,'other':s.FOE,'relation':ALLY},
        expected_state_version=session.engine.state.state_version)
    engine=cold(tmp_path,mid)
    from combat.relations import relation as current_relation
    from combat.ext.creature_kinds import matches
    foe=engine.state.actors[s.FOE]
    assert current_relation(engine,engine.state.actors[s.OWNER],foe)==ALLY
    assert foe.current_hp<foe.maximum_hp and matches(foe,['construct'])
    candidates=[(c.source_definition_id,c.target_ids) for c in engine.legal_candidates()
        if 'mason' in c.source_definition_id and 'construct' in c.source_definition_id]
    actions=[a for a in engine.action_catalog.values() if a.owner_id==s.OWNER and a.display_name=='Emergency Repairs: Repair Construct']
    from combat.recipients import allowed
    assert engine.state.current_actor_id==s.OWNER
    assert actions and allowed(engine,engine.state.actors[s.OWNER],foe,actions[0]), (actions,candidates)
    assert any(s.FOE in targets for _,targets in candidates), candidates
    assert not any(s.FOE in o.get('target_ids',[]) for g in table.state(mid)['menu']['actions']
        if g['label']=='Emergency Repairs: Repair Construct (other side)' for o in g['options'])
    # The printed ally action permits neutral Construct recipients too.
    session=combat._load_session(mid)
    combat.change_relations(mid,change={'kind':'ACTOR_RELATION','subject':s.OWNER,'other':s.FOE,'relation':NEUTRAL},
        expected_state_version=session.engine.state.state_version)
    assert any(s.FOE in o.get('target_ids',[]) for g in table.state(mid)['menu']['actions']
        if g['label']=='Emergency Repairs: Repair Construct' for o in g['options'])


def test_dust_cloud_move_is_available_to_ai_and_commits_through_service(tmp_path):
    from combat.gate2_runtime_models import Position
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    combat,table,mid,send,commit=s.fixture(tmp_path,[DUST+'dust_cloud'],wide=True)
    s.place(table,mid,'Dust Cloud',{'x':4,'y':6})
    engine=cold(tmp_path,mid)
    context=build_decision_context(engine,PolicyLibrary(ROOT).for_actor(s.OWNER)[0],for_ai=True)
    from combat.candidate_knowledge import query as observed
    from combat.gate2_runtime_models import Position
    from combat.placement_menu import cells, exact
    root=next(c for c in context.legal_candidates if c.source_definition_id.endswith('.dust_cloud.move'))
    aim=Position(x=6,y=6)
    # Main now issues lazy placement roots to AI seats too. Assert the same
    # specific destination is reachable through BOTH exhaustive and exact
    # knowledge-scoped routes, rather than requiring an eager menu row.
    assert root.metadata.get('placement_picker')
    with observed(engine):
        native=list(cells(engine,root))
        move=exact(engine,root,aim)
    assert move is not None and move.destination==aim
    assert any(c.candidate_id==move.candidate_id and c.destination==aim for c in native)
    class FixedController:
        def choose_primary_action(self,ctx):
            from combat.gate4_adapters import ManualControllerAdapter
            # Controller changes issue a fresh decision. Select its native
            # option, then provide the same exact aim through the lazy route.
            current=next(c for c in ctx.legal_candidates if c.source_definition_id==move.source_definition_id
                and (c.metadata.get('placement_picker') or c.destination==aim))
            choice=ManualControllerAdapter(lambda _ctx:(current.candidate_id,())).choose_primary_action(ctx)
            if current.metadata.get('placement_picker'):
                choice=choice.model_copy(update={'intent':choice.intent.model_copy(update={
                    'placement_destination':aim})})
            return choice
    combat.controller=FixedController()
    combat.set_controller_mode(mid,actor_id=s.OWNER,controller_mode='LOCAL_AUTO')
    result=combat.local_step(mid)
    assert result['status']=='COMMITTED'
    engine=cold(tmp_path,mid)
    assert next(z for z in engine.state.zones.values() if z.active and DUST+'dust_cloud' in z.source_definition_id).center.x==6


def test_reinforcement_pill_names_object_threshold_and_expiry(monkeypatch,tmp_path):
    combat,table,mid,send,commit=mason_fixture(monkeypatch,tmp_path)
    oid=next(iter(cold(tmp_path,mid).state.objects))
    commit(s.candidate(table,mid,'Emergency Repairs: Reinforce Position',oid))
    condition=next(c for c in cold(tmp_path,mid).state.actors[s.OWNER].conditions.values()
        if c.condition_id=='condition:typed.mason_reinforcement')
    label=condition.data['label']
    assert 'wall' in label.lower() and 'Damage Threshold +4' in label
    assert 'hits below its threshold' in label and 'next turn start' in label


@pytest.mark.parametrize('construct', ['ally','enemy',None])
def test_repair_construct_does_not_heal_ordinary_creatures(monkeypatch,tmp_path,construct):
    from combat.canonical import canonical_sha256
    original=s.sheet;calls=[]
    def sheet(mids,**kwargs):
        doc=original(mids,**kwargs)
        if len(calls)==(2 if construct=='ally' else 1) and construct:doc['identity']['creature_type']='construct'
        calls.append(1);return doc
    monkeypatch.setattr(s,'sheet',sheet)
    def add(bundles):
        b=bundles[0];action={'source_definition_id':'test:mason.damage_construct','display_name':'Chip construct',
            'owner_id':s.OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'ANY_CREATURE','range_ft':60,
            'parameters':{'free_primary':True,'typed':{'source':'test:mason.damage','numbers':{},'duration':{'kind':'instant'},
                'effects':[{'type':'damage','applies_to':'target','flat':40,'damage_types':['force']}]}}}
        b['action_catalog'].append(action);b['actor_template']['action_ids'].append(action['source_definition_id'])
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid,send,commit=s.fixture(tmp_path,[MASON],allies=(s.SECOND,),
        positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':4,'y':6},s.SECOND:{'x':4,'y':7}},bundle_transform=add)
    recipient=s.SECOND if construct!='enemy' else s.FOE
    commit(s.candidate(table,mid,'Chip construct',recipient))
    if not construct:
        assert not any('Repair Construct' in g['label'] for g in table.state(mid)['menu']['actions'])
        return
    qi=cold(tmp_path,mid).state.actors[s.OWNER].resources['resource:core.qi']
    label='Emergency Repairs: Repair Construct (other side)' if construct=='enemy' else 'Emergency Repairs: Repair Construct'
    commit(s.candidate(table,mid,label,recipient));engine=cold(tmp_path,mid)
    healing=next(e for e in engine.events if e.event_type=='HEALING_APPLIED' and e.actor_id==s.OWNER)
    assert engine.state.actors[recipient].current_hp==460+healing.payload['offered']
    roll=next(e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and 'HEALING:' in str(e.payload.get('reason')))
    assert roll.payload['modifier']==2
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==qi-2
    assert not any(e.event_type=='GM_RIDER' and 'mason' in e.source_definition_id for e in engine.events)


def test_dust_cloud_free_move_is_zone_only_and_once_per_turn(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[DUST+'dust_cloud'],wide=True)
    position=cold(tmp_path,mid).state.actors[s.OWNER].position
    s.place(table,mid,'Dust Cloud',{'x':4,'y':6})
    qi=cold(tmp_path,mid).state.actors[s.OWNER].resources['resource:core.qi']
    s.place(table,mid,'Dust Cloud: move',{'x':6,'y':6})
    engine=cold(tmp_path,mid)
    assert engine.state.actors[s.OWNER].position==position
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==qi
    assert next(z for z in engine.state.zones.values() if z.active and DUST+'dust_cloud' in z.source_definition_id).center.x==6
    assert not any(g['label']=='Dust Cloud: move' for g in table.state(mid)['menu']['actions'])


def test_other_casters_dust_cloud_does_not_penalize_choking_save(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[DUST+'choking_dust'],foe_talents=[DUST+'dust_cloud'],wide=True)
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.FOE:commit(table.state(mid)['menu']['end_turn'])
    s.place(table,mid,'Dust Cloud',{'x':4,'y':6})
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    commit(s.candidate(table,mid,'Choking Dust: Choking Mode',s.FOE));engine=cold(tmp_path,mid)
    assert not any(e.event_type=='DAMAGE_ROLLED' and 'DUST_CLOUD_PENALTY' in str(e.payload.get('reason')) for e in engine.events)
