"""Water contracts through table commits, session execute_intent and cold replay."""
from copy import deepcopy
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload, sealed_native_attack, act
from tests.test_auto38_water import soaked
STILL='TAL_WATER_STILL_SURFACE_METHOD'
TIDAL='insight.tidal-body'
WAVE='TAL_WATER_WAVE_BURST'
USES='resource:uses.water_still_surface'


def attacks(bundles, *, uses=None, blind=False, sight=True, large=False):
    for b in bundles:
        if b['actor_id']==OWNER:
            b['actor_template']['saving_throws']['DEX']=-100
        if b['actor_id']==FOE:
            if large:
                from tests.cw2_service_support import add_action, seal
                add_action(b,'Prepare Large attacker',[{'type':'size_change','size':'Large',
                    'applies_to':'self','expires_on':'UNTIL_REMOVED'}],target='SELF')
                seal(b)
            sealed_native_attack(b,'Ranged fixture',range_ft=60,attack_bonus=0)
            b['action_catalog'][-1]['parameters']['requires_sight']=sight
            for a in b['action_catalog']:
                typed=a.get('parameters',{}).get('typed',{})
                if typed.get('source')=='INK_BASE_INK_LASH':
                    typed['numbers']['attack_bonus']=100
            if blind: b.setdefault('senses',{'rows':[]})['rows'].append({'sense':'blindsight','range_ft':60})
        if uses is not None and b['actor_id']==OWNER:
            for r in b['actor_template']['resources']:
                if r['resource_id']==USES: r['initial']=uses
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)


def prepare(bundles, *, save=100, attack=100):
    for b in bundles:
        for a in b['action_catalog']:
            t=a.get('parameters',{}).get('typed',{})
            if t.get('source')=='WATER_BASE_WATER_LASH':t['numbers']['attack_bonus']=attack
        b['actor_template']['saving_throws']['STR']=save
        if b['actor_id']==OWNER:
            a=deepcopy(next(a for a in b['action_catalog'] if a.get('parameters',{}).get('typed',{}).get('source')=='WATER_BASE_WATER_LASH'))
            a.update(source_definition_id='action:test.a2_soak',display_name='Fixture soak',economy='NONE',target_kind='ANY_CREATURE')
            a['parameters']['typed'].update(source='test_a2_soak',riders=[],effects=[{'type':'mark','mark':'Soaked','applies_to':'target','duration':{'kind':'until_end_of_your_next_turn'}}])
            a['parameters']['expected_damage']=0
            b['action_catalog'].append(a);b['actor_template']['action_ids'].append(a['source_definition_id'])
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)


@pytest.mark.parametrize('pick',['free','cp',None])
def test_still_surface_payment_decline_and_rollback(tmp_path,pick):
    combat,table,mid=fixture(tmp_path,[STILL],bundle_transform=attacks)
    settle(table,mid,candidate(combat,mid,'Shape Current: Mist Basin',at=(4,6)).candidate_id)
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.model_dump(mode='json')
    c=candidate(combat,mid,'Ranged fixture',target=ALLY)
    assert act(table,mid,c.candidate_id)['status']=='REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json')==before
    prompts=settle(table,mid,c.candidate_id,{'choice:needle.water_still_surface':pick})
    assert any(p['context']['reactor_id']==OWNER for p in prompts)
    if pick == 'free':
        prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.water_still_surface')
        assert prompt['action']=='Ranged fixture'
        assert prompt['affected']==combat._load_session(mid).engine.state.actors[ALLY].display_name
        assert 'Ranged fixture' in prompt['trigger'] and 'worker2-foe' not in prompt['trigger']
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources[USES]==4-int(pick=='free')
    assert e.state.actors[OWNER].resources['resource:core.qi']==99-int(pick=='cp')
    assert e.state.actors[OWNER].reaction_available==(pick is None)
    roll=next(v for v in reversed(e.events) if v.event_type=='ATTACK_ROLLED' and v.actor_id==FOE)
    assert roll.payload['mode']==('DISADVANTAGE' if pick else 'NORMAL')


@pytest.mark.parametrize('case',['outside_target','inside_attacker','no_basin','no_owner','sightless','blindsight','empty_free','large_attacker'])
def test_still_surface_geometry_senses_ownership_exhausted_uses(tmp_path,case):
    talents=['WATER_BASE_SHAPE_CURRENT'] if case=='no_owner' else [STILL]
    combat,table,mid=fixture(tmp_path,talents,
        foe_position={'x':4,'y':5} if case=='inside_attacker' else None,
        positions=({'actor:factory.worker2-owner':{'x':3,'y':6},'actor:factory.worker2-ally':{'x':7,'y':7},
                    'actor:factory.worker2-foe':{'x':5,'y':5}} if case=='large_attacker' else None),
        bundle_transform=lambda bs:attacks(bs,uses=0 if case=='empty_free' else None,large=case=='large_attacker',
                                           blind=case=='blindsight',sight=case!='sightless'))
    if case!='no_basin':
        settle(table,mid,candidate(combat,mid,'Shape Current: Mist Basin',at=(7,7) if case in {'outside_target','large_attacker'} else (4,6)).candidate_id)
    turn(table,mid,FOE)
    if case=='large_attacker':
        settle(table,mid,candidate(combat,mid,'Prepare Large attacker').candidate_id)
        e=reload(tmp_path,mid)
        from combat.space import point
        zone=next(z for z in e.state.zones.values() if z.active and z.owner_id==OWNER)
        cells={point(cell) for cell in zone.affected_cells}
        assert point(e.state.actors[FOE].position) not in cells
        assert set(e._actor_volume(e.state.actors[FOE])) & cells
    prompts=settle(table,mid,candidate(combat,mid,'Ranged fixture',target=ALLY).candidate_id,
                   {'choice:needle.water_still_surface':'cp' if case=='empty_free' else 'free'})
    e=reload(tmp_path,mid)
    receipt=[v for v in e.events if v.event_type=='REACTION_RESOLVED' and v.source_definition_id==STILL]
    assert bool(receipt)==(case=='empty_free')
    assert any(p['context']['reaction_source_id']=='choice:needle.water_still_surface' for p in prompts)==(case=='empty_free')
    if case=='empty_free':
        assert receipt[-1].payload['payment']=='cp'
        assert e.state.actors[OWNER].resources[USES]==0
        assert e.state.actors[OWNER].resources['resource:core.qi']==98


def test_still_surface_ai_protects_ally(tmp_path):
    combat,table,mid=fixture(tmp_path,[STILL],bundle_transform=attacks)
    settle(table,mid,candidate(combat,mid,'Shape Current: Mist Basin',at=(4,6)).candidate_id)
    turn(table,mid,FOE)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    settle(table,mid,candidate(combat,mid,'Ranged fixture',target=ALLY).candidate_id)
    e=reload(tmp_path,mid)
    assert any(v.source_definition_id==STILL and v.target_ids==(ALLY,) for v in e.events if v.event_type=='REACTION_RESOLVED')
    assert e.state.actors[OWNER].resources[USES]==3


@pytest.mark.parametrize('remote_inside,physical_inside',[(True,False),(False,True)])
def test_still_surface_uses_remote_attack_origin_through_table_reload(tmp_path,remote_inside,physical_inside):
    ink='tianxia.talent.ink.marked_origin'
    basin_at=(5,7) if remote_inside else (7,6)
    ally_at=(7,7) if remote_inside else (7,6)
    foe_at=(4,6)
    combat,table,mid=fixture(tmp_path,[STILL,'WATER_BASE_SHAPE_CURRENT'],
        foe_sheet=sheet(['INK_BASE_PRESS_MARK','INK_BASE_INK_LASH',ink],cl=15),
        positions={OWNER:{'x':5 if remote_inside else 3,'y':6},ALLY:{'x':ally_at[0],'y':ally_at[1]},FOE:{'x':foe_at[0],'y':foe_at[1]}},
        bundle_transform=attacks)
    settle(table,mid,candidate(combat,mid,'Shape Current: Mist Basin',at=basin_at).candidate_id)
    end=table.state(mid)['menu']['end_turn'];settle(table,mid,end)
    turn(table,mid,FOE)
    # Mark the Basin owner with the real Press Mark action, then move the
    # attacker so its physical body is on the opposite side from that anchor.
    settle(table,mid,candidate(combat,mid,'Press Mark',target=OWNER).candidate_id)
    marked=reload(tmp_path,mid)
    from combat.typed_executor import bears_mark
    assert bears_mark(marked.state.actors[OWNER],FOE,'ink_mark')
    turn(table,mid,OWNER);settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,FOE)
    foe_destination=(8,6) if remote_inside else (6,6)
    move=next(c for c in combat._load_session(mid).engine.legal_candidates()
              if c.kind.value=='MOVE' and c.destination==Position(x=foe_destination[0],y=foe_destination[1]))
    settle(table,mid,move.candidate_id)
    turn(table,mid,OWNER);settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,FOE)
    remote=candidate(combat,mid,'Ink Lash',target=ALLY,remote=True)
    e=combat._load_session(mid).engine
    zone=next(z for z in e.state.zones.values() if z.active and z.owner_id==OWNER)
    from combat.space import point
    zone_volume={point(cell) for cell in zone.affected_cells}
    origin=point(Position(**remote.metadata['effect_origin']['position']))
    assert remote.metadata['effect_origin']['position']==e.state.actors[OWNER].position.model_dump(mode='json')
    assert (origin in zone_volume) is remote_inside
    assert bool(set(e._actor_volume(e.state.actors[FOE])) & zone_volume) is physical_inside
    result=act(table,mid,remote.candidate_id)
    prompted=result['status']=='REACTION_REQUIRED'
    assert prompted is (not remote_inside)
    if prompted:
        settle(table,mid,remote.candidate_id,{'choice:needle.water_still_surface':'free'})
    loaded=reload(tmp_path,mid)
    receipts=[v for v in loaded.events if v.event_type=='REACTION_RESOLVED' and v.source_definition_id==STILL]
    assert bool(receipts)==(not remote_inside)


def tidal_bundle():
    document=sheet([WAVE]);document['spheres_and_talents']['cultivation_insight_record_ids']=[TIDAL]
    document['ability_scores_and_statistics']['primary_resource']['maximum']=100
    return compile_character(document,actor_id=OWNER,reaction_plan={'ask':True})


@pytest.mark.parametrize('accept',[True,False])
def test_tidal_body_consent_next_start_hp_expiry(tmp_path,accept):
    combat,table,mid=fixture(tmp_path,[WAVE],owner_bundle=tidal_bundle(),bundle_transform=lambda bs:prepare(bs,save=100))
    prompts=settle(table,mid,candidate(combat,mid,'Shape Current: Flowing Current + Wave Burst',at=(4,6)).candidate_id,
        {'choice:needle.area_recipients':[OWNER],'choice:needle.water_tidal_body':'keep' if accept else None})
    assert any(p['context']['reaction_source_id']=='choice:needle.water_tidal_body' for p in prompts)
    prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.water_tidal_body')
    assert prompt['action']=='Shape Current: Flowing Current + Wave Burst'
    assert prompt['affected']==combat._load_session(mid).engine.state.actors[OWNER].display_name
    assert 'Shape Current: Flowing Current + Wave Burst' in prompt['trigger']
    e=reload(tmp_path,mid)
    assert soaked(e.state.actors[OWNER]) and e.state.actors[OWNER].temporary_hp==0
    turn(table,mid,FOE);turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].temporary_hp==(4 if accept else 0)
    assert soaked(e.state.actors[OWNER])==(not accept)


@pytest.mark.parametrize('case',['choose','decline','dry','miss','pull'])
def test_lash_optional_five_foot_destination_pull_replacement(tmp_path,case):
    talents=['TAL_WATER_PULL_OF_THE_RIVER'] if case=='pull' else ['TAL_WATER_WATER_WHIP']
    combat,table,mid=fixture(tmp_path,talents,bundle_transform=lambda bs:prepare(bs,attack=-100 if case=='miss' else 100))
    if case!='dry': settle(table,mid,candidate(combat,mid,'Fixture soak',target=FOE).candidate_id)
    prompts=settle(table,mid,candidate(combat,mid,'Water Lash + Pull of the River' if case=='pull' else 'Water Lash',target=FOE).candidate_id,
        {'choice:needle.water_lash_shift':'step:6,7' if case=='choose' else None,
         'choice:needle.water_whip':None,'choice:needle.water_pull_of_river':None})
    e=reload(tmp_path,mid)
    offered=any(p['context']['reaction_source_id']=='choice:needle.water_lash_shift' for p in prompts)
    assert offered==(case in {'choose','decline'})
    assert (e.state.actors[FOE].position.x,e.state.actors[FOE].position.y)==((6,7) if case=='choose' else (6,6))
    assert e.state.actors[FOE].movement_remaining_ft==30


def test_lash_preserves_remaining_printed_extra_attacks(tmp_path):
    from tests.test_carry import KIT
    combat,table,mid=fixture(tmp_path,['WATER_BASE_WATER_LASH'],cl=11,
        owner_features=('tianxia.path.body_refining.feature.extra_attack',),
        owner_kit={'starting_kit':{'items':[KIT['items'][-1]]}},bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Water Lash',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].turn_flags['special_attack_rest']==2
    assert not e.state.actors[OWNER].action_available
    rest=next(a.display_name for a in e.action_catalog.values() if a.parameters.get('attack_action_rest'))
    settle(table,mid,candidate(combat,mid,rest,target=FOE).candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].turn_flags['special_attack_rest']==1


def footwork_fixture(tmp_path, *, owned=True, ally_start=(4,6), foe_start=(6,6), owner_start=None,
                     large_foe=False, flying_ally=False, liquid_body=False, foe_reacts=True, foe_ally=False):
    import json, zipfile
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    from tests.cw2_service_support import add_action, seal
    court='TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
    ids=[OWNER,ALLY,FOE]
    wide=ally_start[0]==0 or ally_start[0]>=30 or foe_start[0]>=12
    owner_start=owner_start or ((15,15) if wide else (3,6))
    documents={}
    for aid in ids:
        talents=[court] if aid==OWNER else (['TAL_FATE_FATE_SOVEREIGN_INCARNATION'] if aid==ALLY and flying_ally else [])
        doc=sheet(talents,cl=15)
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
        doc['ability_scores_and_statistics']['speed']['walking_ft']=120 if wide and aid==ALLY else 60
        if aid==OWNER and owned:
            doc['spheres_and_talents']['cultivation_insight_record_ids']=['insight.tide-court-footwork']
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
        documents[aid]=doc
    combat=CombatService(ROOT,tmp_path)
    width,height=(32,32) if wide else (12,14)
    corridor_y=15 if wide else 6
    lower,upper=((14,17) if large_foe else ((8,18) if foe_start[0]==17 else (14,16))) if wide else (6,7)
    walls=[{'shape':'rect','points':[[0,0],[width,lower]]},
           {'shape':'rect','points':[[0,upper],[width,height]]}]
    if large_foe:
        # Keep the 2x2 hostile's two-row corridor local so the test cannot
        # route around its outside-Court cell through the otherwise open map.
        walls.append({'shape':'rect','points':[[26,14],[29,15]]})
    combat.tabletop_maps.save({'display_name':'Water footwork hall','width_squares':width,'height_squares':height,
        'walls':walls,
        'starts':{'team1':[list(owner_start),list(ally_start)],'team2':[list(foe_start)]}})
    bundles=[compile_character(documents[aid],actor_id=aid,
        reaction_plan={'ask':aid==FOE and foe_reacts}) for aid in ids]
    if large_foe:
        from tests.cw2_service_support import add_action, seal
        foe=next(b for b in bundles if b['actor_id']==FOE)
        add_action(foe,'Prepare Large hostile',[{'type':'size_change','size':'Large',
            'applies_to':'self','expires_on':'UNTIL_REMOVED'}],target='SELF')
        seal(foe)
    if flying_ally:
        from tests.cw2_service_support import add_action, seal
        ally=next(b for b in bundles if b['actor_id']==ALLY)
        add_action(ally,'Fixture flight cannot ascend',[{'type':'condition','condition':'flight_limited',
            'applies_to':'self','condition_data':{'cannot_gain_altitude':1},'expires_on':'UNTIL_REMOVED'}],target='SELF')
        seal(ally)
    if liquid_body:
        # An independent whole-footprint passage grant from another sphere, to
        # check it survives a Water Court this ally was also selected into.
        ally=next(b for b in bundles if b['actor_id']==ALLY)
        add_action(ally,'Fixture Liquid Body',[{'type':'creature_passage','applies_to':'self',
            'expires_on':'UNTIL_REMOVED'}],target='SELF')
        seal(ally)
    arena=combat.factory_arenas(include_retired=True)['battlefield:map.water-footwork-hall']
    positions={OWNER:{'x':owner_start[0],'y':owner_start[1]},
               ALLY:{'x':ally_start[0],'y':ally_start[1]},
               FOE:{'x':foe_start[0],'y':foe_start[1]}}
    side='team:factory' if foe_ally else 'team:opponents'
    mid=combat._finish_factory_match(bundles,ids,{OWNER:'team:factory',ALLY:'team:factory',FOE:side},
        positions,arena,[OWNER,ALLY],[] if foe_ally else [FOE],control_modes={aid:'MANUAL' for aid in ids},
        match_seed='A2WATER-FOOTWORK',display_name='A2WATER Footwork scope regression',maximum_rounds=15)['match_id']
    table=TabletopService(combat,tmp_path)
    if large_foe:
        turn(table,mid,FOE)
        settle(table,mid,candidate(combat,mid,'Prepare Large hostile').candidate_id)
        grown=reload(tmp_path,mid)
        assert grown._footprint(grown.state.actors[FOE]).width_cells==2
    turn(table,mid,OWNER)
    return combat,table,mid


@pytest.mark.parametrize('selected',[True,False])
def test_tide_footwork_selects_allies_and_native_crossing_once_per_round(tmp_path,selected):
    from combat.gate2_runtime_models import Position
    combat,table,mid=footwork_fixture(tmp_path)
    prompts=settle(table,mid,candidate(combat,mid,'Court of the Endless Tide',target=OWNER).candidate_id,
        {'choice:needle.water_tide_footwork':[ALLY] if selected else []})
    prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.water_tide_footwork')
    assert [o['id'] for o in prompt['choice']['options']]==[ALLY]
    e=reload(tmp_path,mid)
    z=next(z for z in e.state.zones.values() if z.active and z.owner_id==OWNER)
    assert e._footprint_intersects(e.state.actors[FOE],z.affected_cells)
    assert z.trigger_profile['water_tide_footwork_allies']==([ALLY] if selected else [])
    turn(table,mid,ALLY)
    e=reload(tmp_path,mid)
    moves=[c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination==Position(x=7,y=6)]
    assert bool(moves)==selected
    assert not any(c.kind.value=='MOVE' and c.destination==e.state.actors[FOE].position for c in e.legal_candidates())
    if not selected:
        return
    assert Position(x=6,y=6) in moves[0].canonical_path
    assert moves[0].movement_cost_ft==20
    settle(table,mid,moves[0].candidate_id)
    e=reload(tmp_path,mid)
    assert soaked(e.state.actors[FOE]) and not soaked(e.state.actors[ALLY])
    assert e.state.actors[ALLY].position==Position(x=7,y=6)
    return_move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination==Position(x=4,y=6))
    settle(table,mid,return_move.candidate_id)
    e=reload(tmp_path,mid)
    receipts=[v for v in e.events if v.event_type=='PASSIVE_TRIGGERED' and v.source_definition_id=='insight.tide-court-footwork']
    assert len(receipts)==1 and receipts[0].target_ids==(FOE,)


def test_tide_footwork_reselection_can_end_grant(tmp_path):
    from combat.gate2_runtime_models import Position
    combat,table,mid=footwork_fixture(tmp_path)
    settle(table,mid,candidate(combat,mid,'Court of the Endless Tide',target=OWNER).candidate_id)
    settle(table,mid,candidate(combat,mid,'Tide-Court Footwork: choose allies',target=OWNER).candidate_id,
        {'choice:needle.water_tide_footwork':[]})
    turn(table,mid,ALLY)
    e=reload(tmp_path,mid)
    assert not any(c.kind.value=='MOVE' and c.destination==Position(x=7,y=6) for c in e.legal_candidates())


def test_tide_footwork_designates_ally_before_entering_court(tmp_path):
    combat,table,mid=footwork_fixture(tmp_path,ally_start=(2,15),foe_start=(17,15),owner_start=(15,10))
    prompts=settle(table,mid,candidate(combat,mid,'Court of the Endless Tide',target=OWNER).candidate_id,
        {'choice:needle.water_tide_footwork':[ALLY]})
    prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.water_tide_footwork')
    assert [o['id'] for o in prompt['choice']['options']]==[ALLY]
    e=reload(tmp_path,mid)
    z=next(z for z in e.state.zones.values() if z.active and z.owner_id==OWNER)
    assert not e._footprint_intersects(e.state.actors[ALLY],z.affected_cells)
    assert e._footprint_intersects(e.state.actors[FOE],z.affected_cells)
    # Advancing from outside can still use the Court crossing around its
    # hostile occupant; the route is committed and its consequences survive replay.
    turn(table,mid,ALLY)
    e=reload(tmp_path,mid)
    # Submit an explicit route through the hostile so the regression exercises
    # the service preview/execute path rather than whichever route is shortest.
    session=combat._load_session(mid)
    context=combat._decision_model(session)
    path=[Position(x=x,y=15) for x in range(2,19)]
    from combat.movement_routes import context_for_payload
    payload={'actor_id':ALLY,'decision_id':context.decision_id,'state_version':context.state_version,
        'target_ids':[],'destination':path[-1].model_dump(mode='json'),
        'movement_path':[p.model_dump(mode='json') for p in path],'movement_mode':'walk'}
    routed=context_for_payload(session.engine,context,payload)
    route_candidate=next(c for c in routed.legal_candidates if c.metadata.get('explicit_movement_path'))
    payload['candidate_id']=route_candidate.candidate_id
    combat.submit_intent(mid,payload,[],None,session=session)
    e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].position==Position(x=18,y=15)
    assert soaked(e.state.actors[FOE])


@pytest.mark.parametrize('flying',[False,True])
def test_tide_footwork_does_not_open_large_hostile_cells_outside_court(tmp_path,flying):
    combat,table,mid=footwork_fixture(tmp_path,ally_start=(31,15),foe_start=(27,15),large_foe=True,
                                      flying_ally=flying)
    settle(table,mid,candidate(combat,mid,'Court of the Endless Tide',target=OWNER).candidate_id,
        {'choice:needle.water_tide_footwork':[ALLY]})
    turn(table,mid,ALLY)
    if flying:
        settle(table,mid,candidate(combat,mid,'Fate-Sovereign Incarnation: Attack Penalty').candidate_id)
        settle(table,mid,candidate(combat,mid,'Fixture flight cannot ascend',target=ALLY).candidate_id)
    e=reload(tmp_path,mid)
    z=next(z for z in e.state.zones.values() if z.active and z.owner_id==OWNER)
    foe=e.state.actors[FOE]
    court={(cell.x,cell.y) for cell in z.affected_cells}
    footprint=set(e._actor_cells(foe))
    assert footprint & court and footprint - court
    # The route would cross only the Large hostile's outside-Court cell. The
    # old whole-footprint grant incorrectly exposed this endpoint as reachable.
    destination=Position(x=25,y=15,z=0)
    moves=[c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination==destination]
    assert not moves, [(m.destination.model_dump(), [p.model_dump() for p in m.canonical_path],
                       sorted(footprint-court), sorted(footprint&court)) for m in moves]


def test_tide_footwork_ai_court_selects_only_allies_with_enemy_in_range(tmp_path):
    # Restrict only the fixture's starting catalog choices, leaving the genuine
    # Court effect, policy, recipient selection and table AI execution intact.
    def only_court(bundles):
        for b in bundles:
            if b['actor_id']==OWNER:
                b['actor_template']['action_ids']=[a['source_definition_id'] for a in b['action_catalog']
                    if a.get('parameters',{}).get('typed',{}).get('source')=='TAL_WATER_COURT_OF_THE_ENDLESS_TIDE']
                # The sheet compiler defaults a zero walking Speed to 30.
                # Seal an immobile fixture so the actual AI casts with both
                # ally and enemy in its Court instead of relocating first.
                b['actor_template']['speed_ft']=0
                b['carrying'].update(speed_ft=0,template_speed_ft=0)
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    document=sheet(['TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'],cl=15)
    document['ability_scores_and_statistics']['speed']['walking_ft']=0
    document['spheres_and_talents']['cultivation_insight_record_ids']=['insight.tide-court-footwork']
    document['ability_scores_and_statistics']['primary_resource']['maximum']=100
    owned=compile_character(document,actor_id=OWNER,reaction_plan={'ask':False})
    combat,table,mid=fixture(tmp_path,['TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'],owner_bundle=owned,bundle_transform=only_court)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    for _ in range(8):
        settle(table,mid,None,auto=True)
        e=reload(tmp_path,mid)
        zones=[z for z in e.state.zones.values() if z.active and z.owner_id==OWNER]
        if zones:
            break
    assert zones
    assert e._footprint_intersects(e.state.actors[ALLY],zones[0].affected_cells)
    assert e._footprint_intersects(e.state.actors[FOE],zones[0].affected_cells)
    assert zones[0].trigger_profile['water_tide_footwork_allies']==[ALLY]
