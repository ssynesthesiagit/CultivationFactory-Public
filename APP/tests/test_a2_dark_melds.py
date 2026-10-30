"""Compiled Dark casts through table/session commits, cold service reload and replay."""
import pytest
from combat import senses, zones
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn
from tests.test_r9i_karma_persistence import end_turn

BLIND = 'TAL_DARK_BLINDFOLD'
FEED = 'TAL_DARK_FEED_ON_DARKNESS'


def darkness_affects_everyone(bundles):
    """Opt this immunity fixture into harm to allies under main's area policy."""
    for bundle in bundles:
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Darkness':
                action['parameters']['typed'].setdefault('area', {})[
                    'explicit_harmful_recipients'] = 'every_creature'


def hold_meld_beside_darkness(bundles):
    """Seal these fixtures' concurrent-cast premise, including on public CI.

    The tests retain a concentrating Meld while casting independent Darkness.
    Explicitly select the supported unlimited mode rather than depending on
    whether the external concentration-rules file is in the test export.
    """
    for bundle in bundles[:2]:
        bundle['concentration_rules'] = {'capacity': 'unlimited'}


def cast(combat, table, mid, name, who):
    settle(table, mid, candidate(combat, mid, name, target=who).candidate_id)


def prefer_cast(combat, source):
    # The fixture requests this spell. The real AI still chooses among the
    # engine's candidates and commits its result through the table/session.
    policy, _ = combat.policies.for_actor(OWNER)
    combat._dao_policies[OWNER] = policy.model_copy(
        update={'action_priorities': {source: 100}}).model_dump(mode='json')


def senses_setup(*, base=0, sense='darkvision', no_start=False):
    def transform(bundles):
        if no_start:
            bundles[0]['senses']['meld_start'] = None
        if base:
            bundles[1].setdefault('senses', {})['rows'] = [
                {'feature_id': 'test:ordinary', 'sense': sense, 'range_ft': base, 'when': 'always'}]
    return transform


@pytest.mark.parametrize('base,enhanced,feet', [(0,False,60),(0,True,120),(60,False,90),(60,True,120)])
def test_darkvision_granted_to_ally_and_augment_pays_two_cp(tmp_path, base, enhanced, feet):
    c,t,m = fixture(tmp_path, ['TAL_DARK_DARKVISION'], seed='DARK-VISION',
                    bundle_transform=senses_setup(base=base))
    before = reload(tmp_path,m).state.actors[OWNER].resources['resource:core.qi']
    cast(c,t,m,'Meld: Darkvision' + (' (2 CP)' if enhanced else ''),ALLY)
    e = reload(tmp_path,m)
    assert senses.of(e,e.state.actors[ALLY])['darkvision']['range_ft'] == feet
    assert e.state.actors[OWNER].resources['resource:core.qi'] == before - (2 if enhanced else 0)
    assert not senses.of(e,e.state.actors[FOE]).get('darkvision')
    # The concentration belongs to the caster, not the touched ally.
    assert any(c.data.get('caster_id') == OWNER for c in e.state.actors[ALLY].conditions.values()
               if c.condition_id == senses.MELD)


@pytest.mark.parametrize('dc,applied', [(100,True),(-100,False)])
def test_unwilling_darkvision_has_real_wisdom_save(tmp_path,dc,applied):
    c,t,m = fixture(tmp_path,['TAL_DARK_DARKVISION'],owner_dc=dc,
                    foe_position={'x':3,'y':5},seed='DARK-UNWILLING')
    settle(t,m,candidate(c,m,'Meld: Darkvision',target=FOE).candidate_id,
           picks={'choice:needle.dark_meld_consent': None})
    e=reload(tmp_path,m)
    assert bool(senses.of(e,e.state.actors[FOE]).get('darkvision')) == applied
    assert any(ev.event_type == 'SAVE_ROLLED' and ev.actor_id == FOE for ev in e.events)


@pytest.mark.parametrize('sense,immune', [('scent',False),('tremorsense',False),('darkvision',False),('blindsight',True)])
def test_compiled_blindfold_senses_immunity_and_end_save(tmp_path,sense,immune):
    def transform(bundles):
        bundles[2].setdefault('senses', {})['rows'] = [
            {'feature_id':'test:sense','sense':sense,'range_ft':60,'when':'always'}]
    c,t,m=fixture(tmp_path,[BLIND],owner_dc=100,foe_position={'x':3,'y':5},
                   bundle_transform=transform,seed='DARK-BAND')
    cast(c,t,m,'Meld: Blindfold',FOE)
    e=reload(tmp_path,m); foe=e.state.actors[FOE]
    assert any(c.condition_id=='condition:typed.blinded' for c in foe.conditions.values()) == (not immune)
    assert senses.of(e,foe)[sense]['range_ft'] == (60 if immune else 30)
    turn(t,m,FOE)
    before=len(reload(tmp_path,m).events)
    end_turn(t,m)
    e=reload(tmp_path,m)
    saves=[ev for ev in e.events[before:] if ev.event_type=='SAVE_ROLLED'
           and ev.actor_id==FOE and ev.source_definition_id.endswith('tal_dark_blindfold')]
    assert len(saves) == (0 if immune else 1)


def test_ai_beneficial_meld_only_selects_allies_with_enemy_in_touch_range(tmp_path):
    def transform(bundles):
        owner=bundles[0]
        made=next(a for a in owner['action_catalog'] if a['display_name']=='Meld: Darkvision (2 CP)')
        owner['actor_template']['action_ids']=[made['source_definition_id']]
    c,t,m=fixture(tmp_path,['TAL_DARK_DARKVISION'],foe_position={'x':3,'y':5},
                   bundle_transform=transform,modes={OWNER:'LOCAL_AUTO',ALLY:'MANUAL',FOE:'MANUAL'},seed='DARK-AI')
    e=reload(tmp_path,m)
    rows=[r for r in e.legal_candidates() if e.action_catalog.get(r.source_definition_id) and
          e.action_catalog[r.source_definition_id].display_name=='Meld: Darkvision (2 CP)']
    assert rows and all(r.target_ids[0] in (OWNER,ALLY) for r in rows)
    assert all(r.metadata.get('rider_utility') == 8 for r in rows)
    prefer_cast(c, rows[0].source_definition_id)
    settle(t,m,rows[0].candidate_id,auto=True)
    e=reload(tmp_path,m)
    uses=[ev for ev in e.events if ev.event_type=='INTENT_ACCEPTED' and
          ev.source_definition_id.endswith('.enhanced')]
    assert uses
    assert not senses.of(e,e.state.actors[FOE]).get('darkvision')
    assert any(senses.of(e,e.state.actors[aid]).get('darkvision',{}).get('range_ft') == 120 for aid in (OWNER,ALLY))


@pytest.mark.parametrize('replacement',[0,10,'return'])
def test_feed_grants_at_turn_start_and_expires_one_round_after_departure(tmp_path,replacement):
    def transform(bundles):
        import copy
        hold_meld_beside_darkness(bundles)
        # A known clear outbound and return route fits within this fixture's speed.
        bundles[1]['actor_template']['speed_ft'] = 60
        bundles[1].setdefault('senses', {})['rows']=[{'feature_id':'test:dark-eyes', 'sense':'darkvision','range_ft':60,'when':'always'}]
        owner=bundles[0]
        control=copy.deepcopy(next(a for a in owner['action_catalog'] if a['display_name']=='Meld: Darkvision'))
        control.update(source_definition_id='test:stronger-temp-hp',display_name='Control: Temporary HP',
                       concentration=False,range_ft=120)
        control['parameters']={'typed':{'effects':[{'type':'temp_hp','flat':10,'applies_to':'target'}],
                'numbers':control['parameters']['typed']['numbers'],'duration':{'kind':'instant'},'riders':[]},
                'expected_damage':0}
        owner['action_catalog'].append(control)
        owner['actor_template']['action_ids'].append(control['source_definition_id'])
    c,t,m=fixture(tmp_path,[FEED],seed='DARK-FEED',bundle_transform=transform)
    cast(c,t,m,'Meld: Feed on Darkness',ALLY)
    end_turn(t,m);turn(t,m,OWNER)
    settle(t,m,candidate(c,m,'Darkness',at=(4,6)).candidate_id)
    turn(t,m,ALLY)
    e=reload(tmp_path,m);ally=e.state.actors[ALLY]
    assert ally.temporary_hp == 2
    inside={ (cell.x,cell.y) for z in zones.typed_zones(e) for cell in z.affected_cells }
    assert (1,5) not in inside
    move=next(r for r in t.state(m)['menu']['moves'] if (r['destination']['x'],r['destination']['y'])==(1,5) and not r['destination'].get('z'))
    settle(t,m,move['candidate_id'])
    e=reload(tmp_path,m)
    assert e.state.actors[ALLY].temporary_hp == 2
    assert (e.state.actors[ALLY].position.x,e.state.actors[ALLY].position.y)==(1,5)
    assert any(c.data.get('left_clock') for c in e.state.actors[ALLY].conditions.values()
               if c.condition_id=='condition:typed.dark_feed_pool')
    if replacement=='return':
        back=next(r for r in t.state(m)['menu']['moves'] if (r['destination']['x'],r['destination']['y'])==(4,6) and not r['destination'].get('z'))
        settle(t,m,back['candidate_id'])
        e=reload(tmp_path,m)
        assert not any(c.data.get('left_clock') for c in e.state.actors[ALLY].conditions.values()
                       if c.condition_id=='condition:typed.dark_feed_pool')
    end_turn(t,m)
    if replacement==10:
        turn(t,m,OWNER)
        cast(c,t,m,'Control: Temporary HP',ALLY)
        assert reload(tmp_path,m).state.actors[ALLY].temporary_hp == (2 if replacement=='return' else replacement)
    turn(t,m,ALLY)
    assert reload(tmp_path,m).state.actors[ALLY].temporary_hp == (2 if replacement=='return' else replacement)


def test_clearsight_granted_to_ally_follows_casters_concentration(tmp_path):
    import copy
    def transform(bundles):
        # This guard needs a negative effect on an ally after immunity ends.
        # Unscoped harmful areas on current main normally spare allies.
        darkness_affects_everyone(bundles)
        owner=bundles[0]
        for b in bundles[:2]:
            b.setdefault('senses',{})['rows']=[{'feature_id':'test:ordinary','sense':'blindsight','range_ft':60,'when':'always'}]
        owner['concentration_rules']={'capacity':'cultivation_level','limits_by_cl':[[1,1]]}
        # An independently lasting area must remain after the Meld ends.
        area=next(a for a in owner['action_catalog'] if a['display_name']=='Darkness')
        area['concentration']=False
        area['parameters']['typed']['duration']['concentration']=False
        control=copy.deepcopy(next(a for a in owner['action_catalog'] if a['display_name']=='Meld: Clearsight'))
        control.update(source_definition_id='test:replacement-concentration',display_name='Control: Concentration',target_kind='SELF')
        control['parameters']={'typed':{'effects':[], 'numbers':{},'duration':{'kind':'hours','amount':1,'concentration':True},'riders':[]}}
        owner['action_catalog'].append(control)
        owner['actor_template']['action_ids'].append(control['source_definition_id'])
    c,t,m=fixture(tmp_path,['TAL_DARK_CLEARSIGHT','TAL_DARK_PURE_DARKNESS'],
                   ally_talents=['TAL_DARK_PURE_DARKNESS'],bundle_transform=transform,seed='DARK-CLEAR')
    settle(t,m,candidate(c,m,'Shape Darkness: Pure Darkness').candidate_id)
    settle(t,m,candidate(c,m,'Darkness',at=(4,6)).candidate_id)
    end_turn(t,m);turn(t,m,OWNER)
    settle(t,m,candidate(c,m,'Meld: Clearsight',target=ALLY).candidate_id,
           picks={'choice:needle.clearsight_creator_consent': None})
    e=reload(tmp_path,m); ally=e.state.actors[ALLY]
    grant=next(z for z in zones.typed_zones(e) if z.owner_id==OWNER)
    assert zones.clear_sighted(e,grant,ally)
    assert not [r for r in ally.conditions.values() if r.condition_id==zones.ZONE_EFFECT]
    turn(t,m,ALLY)
    settle(t,m,candidate(c,m,'Shape Darkness: Pure Darkness').candidate_id)
    settle(t,m,candidate(c,m,'Darkness',at=(4,6)).candidate_id)
    e=reload(tmp_path,m)
    own=next(z for z in zones.typed_zones(e) if z.owner_id==ALLY)
    assert not zones.clear_sighted(e,own,e.state.actors[ALLY])
    turn(t,m,OWNER)
    cast(c,t,m,'Control: Concentration',OWNER)
    e=reload(tmp_path,m);ally=e.state.actors[ALLY]
    assert any(ev.event_type=='CONCENTRATION_ENDED' and ev.actor_id==OWNER
               and ev.source_definition_id.endswith('.meld.tal_dark_clearsight') for ev in e.events)
    grant=next(z for z in zones.typed_zones(e) if z.owner_id==OWNER)
    assert not zones.clear_sighted(e,grant,ally)
    assert not any(r.condition_id==senses.MELD and r.data.get('talent')=='TAL_DARK_CLEARSIGHT' for r in ally.conditions.values())
    assert any(r.condition_id==zones.ZONE_EFFECT and r.data.get('zone_id')==grant.zone_id for r in ally.conditions.values())


@pytest.mark.parametrize('name,concentrating,cost', [
    ('Meld: Darkvision (2 CP)',True,2),
    ('Meld: Darkvision (Persistent) (2 CP)',False,4)])
def test_enhanced_darkvision_can_be_granted_persistent_from_real_cast(tmp_path,name,concentrating,cost):
    c,t,m=fixture(tmp_path,['TAL_DARK_DARKVISION'],seed='DARK-PERSIST',
                  bundle_transform=hold_meld_beside_darkness)
    before=reload(tmp_path,m).state.actors[OWNER].resources['resource:core.qi']
    cast(c,t,m,name,ALLY)
    e=reload(tmp_path,m); holder=e.state.actors[ALLY]
    marker=next(x for x in holder.conditions.values() if x.condition_id==senses.MELD)
    assert marker.data['concentration'] is concentrating
    assert senses.of(e,holder)['darkvision']['range_ft']==120
    assert e.state.actors[OWNER].resources['resource:core.qi']==before-cost
    assert bool(e.state.actors[OWNER].concentration) is concentrating
    end_turn(t,m);turn(t,m,OWNER)
    settle(t,m,candidate(c,m,'Darkness',at=(6,6)).candidate_id)
    e=reload(tmp_path,m)
    assert senses.of(e,e.state.actors[ALLY])['darkvision']['range_ft']==120


def test_ai_blindfold_only_selects_enemy_with_ally_in_touch_range(tmp_path):
    def transform(bundles):
        owner=bundles[0]
        made=next(a for a in owner['action_catalog'] if a['display_name']=='Meld: Blindfold')
        owner['actor_template']['action_ids']=[made['source_definition_id']]
    c,t,m=fixture(tmp_path,[BLIND],owner_dc=100,foe_position={'x':3,'y':5},
                   bundle_transform=transform,modes={OWNER:'LOCAL_AUTO',ALLY:'MANUAL',FOE:'MANUAL'},seed='DARK-AI-BAND')
    e=reload(tmp_path,m)
    rows=[r for r in e.legal_candidates() if e.action_catalog.get(r.source_definition_id) and
          e.action_catalog[r.source_definition_id].display_name=='Meld: Blindfold']
    assert rows and all(r.target_ids==(FOE,) for r in rows)
    assert all(r.metadata.get('rider_utility') == 8 for r in rows)
    prefer_cast(c, rows[0].source_definition_id)
    settle(t,m,rows[0].candidate_id,auto=True)
    e=reload(tmp_path,m)
    assert any(c.condition_id=='condition:typed.blinded' for c in e.state.actors[FOE].conditions.values())
    assert not any(c.condition_id=='condition:typed.blinded' for a in (OWNER,ALLY) for c in e.state.actors[a].conditions.values())


@pytest.mark.parametrize('talent,name', [('TAL_DARK_DARKVISION','Darkvision'),
    ('TAL_DARK_CLEARSIGHT','Clearsight'),(FEED,'Feed on Darkness')])
@pytest.mark.parametrize('recipient,accept,auto', [(ALLY,False,False),(FOE,True,False),(ALLY,False,True)])
def test_recipient_owns_meld_willingness(tmp_path,talent,name,recipient,accept,auto):
    from tests.test_r9i_karma_persistence import act
    def transform(bundles):
        owner=bundles[0]
        made=next(a for a in owner['action_catalog'] if a['display_name']=='Meld: '+name)
        # AI side eligibility remains intact: the AI case touches its ally.
        owner['actor_template']['action_ids']=[made['source_definition_id']]
        owner.setdefault('senses',{})['meld_start']=talent
    c,t,m=fixture(tmp_path,[talent],owner_dc=-100,foe_position={'x':3,'y':5},
        bundle_transform=transform,seed='DARK-CONSENT',
        modes={OWNER:'LOCAL_AUTO' if auto else 'MANUAL',ALLY:'MANUAL',FOE:'MANUAL'})
    cid=candidate(c,m,'Meld: '+name,target=recipient)
    if auto:
        prefer_cast(c,cid.source_definition_id)
        # Self already has this Meld, so prefer the adjacent recipient.
        result=t.auto_step(m,0,[])
    else:
        result=act(t,m,cid.candidate_id)
    assert result['status']=='REACTION_REQUIRED',result
    prompt=result['reaction']
    assert prompt['context']['reactor_id']==recipient
    assert prompt['context']['reaction_source_id']=='choice:needle.dark_meld_consent'
    assert reload(tmp_path,m).state.actors[recipient].conditions == c._load_session(m).engine.state.actors[recipient].conditions
    settle(t,m,cid.candidate_id,picks={'choice:needle.dark_meld_consent':'accept' if accept else None},auto=auto)
    e=reload(tmp_path,m)
    markers=[x for x in e.state.actors[recipient].conditions.values() if x.condition_id==senses.MELD]
    assert bool(markers)==accept
    saves=[ev for ev in e.events if ev.event_type=='SAVE_ROLLED' and ev.actor_id==recipient]
    assert bool(saves)==(not accept)


def test_feed_two_casters_replace_without_stacking(tmp_path):
    def transform(bundles):
        hold_meld_beside_darkness(bundles)
        for b,mod in zip(bundles,[1,5,0]):
            for a in b['action_catalog']:
                if a['display_name']=='Meld: Feed on Darkness':
                    a['parameters']['typed']['numbers']['key_mod']=mod
    c,t,m=fixture(tmp_path,[FEED],ally_talents=[FEED],bundle_transform=transform,seed='DARK-REPLACE')
    cast(c,t,m,'Meld: Feed on Darkness',ALLY)
    turn(t,m,ALLY)
    cast(c,t,m,'Meld: Feed on Darkness',ALLY)
    e=reload(tmp_path,m)
    markers=[x for x in e.state.actors[ALLY].conditions.values() if x.condition_id==senses.MELD and x.data.get('talent')==FEED]
    assert len(markers)==1
    assert markers[0].data['caster_id']==ALLY
    assert markers[0].data['numbers']['key_mod']==5
    end_turn(t,m);turn(t,m,ALLY)
    settle(t,m,candidate(c,m,'Darkness',at=(4,6)).candidate_id)
    end_turn(t,m);turn(t,m,ALLY)
    assert reload(tmp_path,m).state.actors[ALLY].temporary_hp==5


def test_near_expiry_manual_meld_can_be_renewed(tmp_path):
    def transform(bundles):
        for a in bundles[0]['action_catalog']:
            if a['display_name']=='Meld: Darkvision (Persistent)':
                a['parameters']['typed']['effects'][0]['duration']={'kind':'rounds','amount':2,'concentration':False}
    c,t,m=fixture(tmp_path,['TAL_DARK_DARKVISION'],bundle_transform=transform,seed='DARK-RENEW')
    cast(c,t,m,'Meld: Darkvision (Persistent)',ALLY)
    old=next(x for x in reload(tmp_path,m).state.actors[ALLY].conditions.values() if x.condition_id==senses.MELD)
    end_turn(t,m);turn(t,m,OWNER)
    cast(c,t,m,'Meld: Darkvision (Persistent)',ALLY)
    e=reload(tmp_path,m)
    markers=[x for x in e.state.actors[ALLY].conditions.values() if x.condition_id==senses.MELD]
    assert len(markers)==1 and markers[0].data['end_clock'] != old.data['end_clock']
    end_turn(t,m);turn(t,m,OWNER)
    assert senses.of(reload(tmp_path,m),reload(tmp_path,m).state.actors[ALLY])['darkvision']['range_ft']==60


def test_meld_descriptions_explain_recipient_and_creator_scope(tmp_path):
    c,t,m=fixture(tmp_path,['TAL_DARK_CLEARSIGHT',FEED],seed='DARK-TEXT')
    e=reload(tmp_path,m)
    clear=next(a for a in e.action_catalog.values() if a.display_name=='Meld: Clearsight')
    feed=next(a for a in e.action_catalog.values() if a.display_name=='Meld: Feed on Darkness')
    assert "the caster's Darkness" in clear.parameters['description']
    assert 'does not grant sight' in clear.parameters['description']
    assert "the caster's key ability modifier" in feed.parameters['description']
    cast(c,t,m,'Meld: Clearsight',ALLY)
    assert 'TAL_DARK_CLEARSIGHT' in senses.melds_of(reload(tmp_path,m),reload(tmp_path,m).state.actors[ALLY])


def test_blindfold_successful_repeat_restores_senses(tmp_path):
    c,t,m=fixture(tmp_path,[BLIND],owner_dc=16,foe_position={'x':3,'y':5},
                   bundle_transform=lambda bs: bs[2].setdefault('senses',{}).update(
                       rows=[{'feature_id':'test:ordinary','sense':'scent','range_ft':60,'when':'always'}]),
                   seed='AUTO108-RPT')
    cast(c,t,m,'Meld: Blindfold',FOE)
    e=reload(tmp_path,m)
    assert any(x.condition_id=='condition:typed.blinded' for x in e.state.actors[FOE].conditions.values())
    assert senses.of(e,e.state.actors[FOE])['scent']['range_ft']==30
    turn(t,m,FOE)
    before=len(reload(tmp_path,m).events)
    end_turn(t,m)
    e=reload(tmp_path,m)
    saves=[ev for ev in e.events[before:] if ev.event_type=='SAVE_ROLLED' and ev.actor_id==FOE
           and ev.source_definition_id.endswith('tal_dark_blindfold')]
    assert len(saves)==1
    assert not any(x.condition_id=='condition:typed.blinded' for x in e.state.actors[FOE].conditions.values())
    assert senses.of(e,e.state.actors[FOE])['scent']['range_ft']==60


@pytest.mark.parametrize('talent,name', [('TAL_DARK_DARKVISION','Darkvision'),
    ('TAL_DARK_CLEARSIGHT','Clearsight'),(FEED,'Feed on Darkness')])
@pytest.mark.parametrize('recipient,accepted',[(ALLY,True),(FOE,False)])
def test_ai_recipient_decides_its_own_meld(tmp_path,talent,name,recipient,accepted):
    c,t,m=fixture(tmp_path,[talent],owner_dc=-100,foe_position={'x':3,'y':5},seed='DARK-AI-RECIPIENT',
        modes={OWNER:'MANUAL',ALLY:'LOCAL_AUTO',FOE:'LOCAL_AUTO'})
    prompts=settle(t,m,candidate(c,m,'Meld: '+name,target=recipient).candidate_id)
    assert not [p for p in prompts if p['context']['reaction_source_id']=='choice:needle.dark_meld_consent']
    e=reload(tmp_path,m)
    assert any(x.condition_id==senses.MELD for x in e.state.actors[recipient].conditions.values())==accepted
    assert any(ev.event_type=='SAVE_ROLLED' and ev.actor_id==recipient for ev in e.events)==(not accepted)
