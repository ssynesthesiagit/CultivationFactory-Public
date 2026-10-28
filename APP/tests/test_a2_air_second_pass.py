"""Air second pass through real service intents, persisted state and cold replay."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight as service_fight, act, resolve, reload, turn, cell_send
from tests.cw2_service_support import add_action
from tests.test_auto27_sniper import BOW
WIND_LINE = 'insight.wind-line-archer'
CLOUD_STEP = 'insight.cloud-step-novice'
DIRECTION = 'air_current_direction'
from combat.ext.air_currents import SKY_ROAD, DESIGNATED

GATHER = 'AIR_BASE_GATHER_CURRENT'
FEATHER = 'TAL_AIR_FEATHER_FALL_BREATH'
WIND_BODY = 'TAL_AIR_WIND_BORNE_BODY'


def fight(tmp_path, talents, **kwargs):
    def insights(doc, aid):
        fields = doc.setdefault('spheres_and_talents', {})
        ids = fields.get('learned_talent_record_ids', [])
        fields['cultivation_insight_record_ids'] = [k for k in ids if k.startswith('insight.')]
        fields['learned_talent_record_ids'] = [k for k in ids if not k.startswith('insight.')]
    return service_fight(tmp_path, talents, sheet_edit=insights, **kwargs)


def move_to(combat, table, mid, xyz):
    def send(answers):
        e = combat._load_session(mid).engine
        c = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
                 and (c.destination.x, c.destination.y, c.destination.z) == xyz)
        s = table.state(mid); m = s['menu']
        return table.act(mid, c.candidate_id, m['decision_id'], m['state_version'], s['last_sequence'], answers)
    return send


def bow_edit(other_penalty=False, hit=True, size='Medium'):
    def edit(bundle):
        if bundle['actor_id'] == RIGHT:
            bundle['actor_template']['size_category'] = size
        if bundle['actor_id'] != LEFT:
            return
        for a in bundle['action_catalog']:
            typed = a['parameters'].get('typed') or {}
            if typed.get('weapon') and typed.get('long_range_ft'):
                typed.update(range_ft=10, long_range_ft=60, disadvantage=other_penalty)
                typed['numbers']['attack_bonus'] = 100 if hit else -100
                a['range_ft'] = 60
                a['economy'] = 'NONE'  # multiple real strikes test one shared turn allowance
                a['parameters']['free_primary'] = True  # declare this fixture's intentional free activation
    return edit


def bow_name(table, mid):
    engine = table.combat._load_session(mid).engine
    item_id = BOW['items'][0]['item_id']
    return next(g['label'] for g in table.state(mid)['menu']['actions']
                if ((engine.action_catalog[g['source_definition_id']].parameters.get('typed') or {})
                    .get('weapon') or {}).get('implement_id') == item_id)


@pytest.mark.parametrize('owns,other,through,expected', [
    (False, False, True, 'DISADVANTAGE'), (True, False, True, 'NORMAL'),
    (True, True, True, 'DISADVANTAGE'), (True, False, False, 'DISADVANTAGE')])
def test_wind_line_removes_only_long_range_through_owned_current(tmp_path, owns, other, through, expected):
    c,t,m = fight(tmp_path, [GATHER] + ([WIND_LINE] if owns else []), left_kit=BOW,
        bundle_edit=bow_edit(other), positions={LEFT:{'x':3,'y':6},RIGHT:{'x':8,'y':6}})
    resolve(cell_send(t,m,'Gather Current: Carry',(5,6) if through else (3,2)),
            {'choice:needle.wind_line_direction':['south']})
    e = reload(c,m)
    if owns:
        assert any(z.trigger_profile.get(DIRECTION) == [0,1,0] for z in e.state.zones.values())
    resolve(lambda a: act(t,m,bow_name(t,m),a,target_id=RIGHT), {'choice:needle.wind_line_push':[]})
    e = reload(c,m)
    shot = next(v for v in reversed(e.events) if v.event_type == 'ATTACK_ROLLED' and v.actor_id == LEFT)
    assert shot.payload['mode'] == expected
    assert e.state.actors[RIGHT].position.y == 6


@pytest.mark.parametrize('hit,size,decline,moved', [
    (True,'Medium',False,True), (False,'Medium',False,False),
    (True,'Huge',False,False), (True,'Medium',True,False)])
def test_wind_line_push_is_optional_sized_and_once_per_turn(tmp_path, hit, size, decline, moved):
    c,t,m = fight(tmp_path,[GATHER,WIND_LINE],left_kit=BOW,bundle_edit=bow_edit(hit=hit,size=size),
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':6,'y':6}})
    resolve(cell_send(t,m,'Gather Current: Carry',(5,6)), {'choice:needle.wind_line_direction':['south']})
    picks={'choice:needle.wind_line_push':[]} if decline else None
    resolve(lambda a:act(t,m,bow_name(t,m),a,target_id=RIGHT),picks)
    e=reload(c,m)
    assert e.state.actors[RIGHT].position.y == (7 if moved else 6)
    _,p=resolve(lambda a:act(t,m,bow_name(t,m),a,target_id=RIGHT),picks)
    e=reload(c,m)
    assert e.state.actors[RIGHT].position.y == (7 if moved else 6)
    if moved:
        assert not any(q['context']['reaction_source_id']=='choice:needle.wind_line_push' for q in p)
        assert any(v.event_type=='MOVEMENT_COMMITTED' and v.source_definition_id==WIND_LINE for v in e.events)


@pytest.mark.parametrize('delay', [False,True])
def test_cloud_step_self_cushion_drift_and_once_scene_delay(tmp_path, delay):
    c,t,m = fight(tmp_path,[GATHER,WIND_BODY,FEATHER,CLOUD_STEP],
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':8,'y':6}})
    resolve(cell_send(t,m,'Gather Current: Carry',(3,6)))
    resolve(move_to(c,t,m,(3,6,2)))
    picks={'choice:needle.cloud_step_delay':['delay'] if delay else [],
           'choice:needle.cloud_step_drift':['drift:5,6']}
    resolve(lambda a:act(t,m,'end',a),picks)
    e=reload(c,m)
    if delay:
        assert e.state.actors[LEFT].position.z==2
        assert e.state.actors[LEFT].turn_flags['cloud_step_round_scene_used'] is True
        turn(t,m,LEFT)
        resolve(lambda a:act(t,m,'end',a),picks)
        e=reload(c,m)
    assert (e.state.actors[LEFT].position.x,e.state.actors[LEFT].position.z)==(5,0)
    assert not any(h.data.get('flight_suspended') or h.condition_id.endswith('cloud_step_drift')
                   for h in e.state.actors[LEFT].conditions.values())
    assert any(v.event_type=='MOVEMENT_COMMITTED' and v.source_definition_id==CLOUD_STEP for v in e.events)
    assert not any(v.event_type=='GM_RIDER' and 'Cloud-Step' in str(v.payload) for v in e.events)
    if delay:
        turn(t,m,LEFT)
        resolve(cell_send(t,m,'Gather Current: Carry',(5,6)))
        resolve(move_to(c,t,m,(5,6,2)))
        _,prompts=resolve(lambda a:act(t,m,'end',a),
            {'choice:needle.cloud_step_delay':['delay'],'choice:needle.cloud_step_drift':[]})
        assert reload(c,m).state.actors[LEFT].position.z==0
        assert not any(q['context']['reaction_source_id']=='choice:needle.cloud_step_delay' for q in prompts)


def road_setup(bundle):
    bundle['actor_template']['fly_speed_ft']=30
    add_action(bundle,'Ground flight',[{'type':'condition','condition':'test_grounded','applies_to':'self',
        'duration':{'kind':'until_removed'},'condition_data':{'flight_disabled':1}}],target='SELF')
    if bundle['actor_id']==LEFT:
        bundle['actor_template']['saving_throws']['CON']=-100
        add_action(bundle,'Break concentration',[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'self'}],target='SELF')
        add_action(bundle,'Lie down',[{'type':'condition','condition':'prone','applies_to':'self','duration':{'kind':'until_removed'}}],target='SELF')


def cast_road(c,t,m, picks=None, *, ai=False, destination=(6,6,2)):
    def send(answers):
        e=c._load_session(m).engine
        roads=[v for v in e.legal_candidates() if e.action_catalog.get(v.source_definition_id)
            and e.action_catalog[v.source_definition_id].display_name=='Sky Road' and v.destination]
        cast=next((v for v in roads if (v.destination.x,v.destination.y,v.destination.z)==destination), None)
        assert cast is not None, [(v.destination.model_dump(), v.display_name) for v in roads][:30]
        s=t.state(m); menu=s['menu']
        if ai:
            from combat.gate4_adapters import ManualControllerAdapter
            real=c.controller
            class Controller:
                def choose_primary_action(self, context):
                    offered = [v for v in context.legal_candidates
                        if e.action_catalog.get(v.source_definition_id) and
                        e.action_catalog[v.source_definition_id].display_name == 'Sky Road']
                    assert offered, [(v.source_definition_id,v.display_name) for v in context.legal_candidates]
                    return ManualControllerAdapter(lambda _: (offered[0].candidate_id, ())).choose_primary_action(context)
                def __getattr__(self,name):
                    return getattr(real,name)
            c.controller=Controller()
            c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
            return t.auto_step(m,t.state(m)['last_sequence'],answers)
        return t.act(m,cast.candidate_id,menu['decision_id'],menu['state_version'],s['last_sequence'],answers)
    return resolve(send,picks)


def test_sky_road_supports_prone_walking_and_falls_when_concentration_ends(tmp_path):
    c,t,m=fight(tmp_path,[SKY_ROAD],bundle_edit=road_setup,
        positions={LEFT:{'x':3,'y':6,'z':2},RIGHT:{'x':9,'y':3}})
    cast_road(c,t,m)
    resolve(lambda a:act(t,m,'Ground flight',a))
    e=reload(c,m)
    assert e.state.actors[LEFT].position.z==2
    resolve(lambda a:act(t,m,'Lie down',a))
    assert reload(c,m).state.actors[LEFT].position.z==2
    resolve(move_to(c,t,m,(4,6,2)))
    assert reload(c,m).state.actors[LEFT].position.z==2
    resolve(lambda a:act(t,m,'Break concentration',a))
    e=reload(c,m)
    assert e.state.actors[LEFT].position.z==0
    assert any(v.event_type=='MOVEMENT_COMMITTED' and v.payload.get('fall_distance_ft')==10 for v in e.events)


def test_sky_road_table_placement_stops_at_an_authored_wall_and_survives_reload(tmp_path):
    def authored_wall(arena):
        arena['walls'] = [*arena.get('walls', []), {
            'id': 'rw001-solid-wall', 'shape': 'rect', 'points': [[5, 5], [6, 7]],
            'filled': True, 'blocks': 'sight_and_movement'}]

    c,t,m=fight(tmp_path,[SKY_ROAD],arena_edit=authored_wall,
        positions={LEFT:{'x':3,'y':6,'z':2},RIGHT:{'x':9,'y':3}})
    cast_road(c,t,m,destination=(4,6,2))
    e=reload(c,m)
    road=next(z for z in e.state.zones.values() if z.active and z.source_definition_id.endswith(SKY_ROAD))
    assert road.affected_cells
    assert max(cell.x for cell in road.affected_cells) < 5, road.affected_cells
    assert not any(a.owner_id==RIGHT and a.source_definition_id.endswith(SKY_ROAD)
                   for a in e.action_catalog.values())
    resolve(lambda answers:act(t,m,'end',answers))
    reload(c,m)


def test_sky_road_ai_designates_allies_with_enemies_in_range(tmp_path):
    c,t,m=fight(tmp_path,[SKY_ROAD],bundle_edit=road_setup,ally=True,
        positions={LEFT:{'x':3,'y':6,'z':2},ALLY:{'x':4,'y':5,'z':2},RIGHT:{'x':6,'y':6,'z':2}})
    # A primary adapter selects this cast; the real controller answers all recipient decisions.
    cast_road(c,t,m,ai=True)
    e=reload(c,m)
    road=next(z for z in e.state.zones.values() if z.active)
    assert tuple(road.trigger_profile[DESIGNATED])==(ALLY,)
    assert RIGHT not in road.trigger_profile[DESIGNATED]


@pytest.mark.parametrize('dc,expected', [(100,0),(-100,2)])
def test_sky_road_crossing_failure_removes_support_and_success_retains_it(tmp_path,dc,expected):
    def setup(bundle):
        road_setup(bundle)
    def arena(arena):
        # A finite column supports the non-flying visitor outside the road.
        arena['terrain_regions'] = [*(r for r in arena.get('terrain_regions',[]) if r['terrain_type']!='BLOCKED'),
            {'terrain_type':'BLOCKED','cells':[{'x':6,'y':4}], 'height_ft':10,'movement_cost':1}]
    c,t,m=fight(tmp_path,[SKY_ROAD],bundle_edit=setup,arena_edit=arena,left_save_dc=dc,
        positions={LEFT:{'x':3,'y':6,'z':2},RIGHT:{'x':5,'y':4,'z':2}})
    cast_road(c,t,m,{'choice:needle.sky_road_designated':[]})
    turn(t,m,RIGHT)
    resolve(move_to(c,t,m,(6,4,2)))
    resolve(lambda a:act(t,m,'Ground flight',a))
    assert reload(c,m).state.actors[RIGHT].position.z==2
    resolve(move_to(c,t,m,(6,5,2)))
    e=reload(c,m)
    assert e.state.actors[RIGHT].position.z==expected
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT]
    assert len(saves)==1
    if expected==0:
        assert any(v.event_type=='MOVEMENT_COMMITTED' and v.source_definition_id=='system:combat.falling'
                   and v.actor_id==RIGHT for v in e.events)


def test_feather_fall_ai_protects_allies_and_self_but_not_enemies(tmp_path):
    def setup(bundle):
        road_setup(bundle)
        for action in bundle['action_catalog']:
            if action['display_name']=='Break concentration':
                action['parameters']['player_only']=False
    c,t,m=fight(tmp_path,[SKY_ROAD,FEATHER],cl=17,bundle_edit=setup,ally=True,
        positions={LEFT:{'x':3,'y':6,'z':2},ALLY:{'x':4,'y':5,'z':2},RIGHT:{'x':6,'y':6,'z':2}})
    cast_road(c,t,m,{'choice:needle.sky_road_designated':[ALLY,RIGHT]})
    for aid in (LEFT,ALLY,RIGHT):
        turn(t,m,aid)
        resolve(lambda a:act(t,m,'Ground flight',a))
        assert reload(c,m).state.actors[aid].position.z==2
    turn(t,m,LEFT)
    # Ending one shared support surface makes all three fall in one native batch.
    # Real AI responses to a deliberately selected primary action. No recipient answers are supplied.
    from combat.gate4_adapters import ManualControllerAdapter
    real=c.controller
    catalog=c._load_session(m).engine.action_catalog
    class Controller:
        def choose_primary_action(self,context):
            offered=[v for v in context.legal_candidates if catalog.get(v.source_definition_id)
                and catalog[v.source_definition_id].display_name=='Break concentration']
            assert offered, [(v.source_definition_id,v.display_name) for v in context.legal_candidates]
            chosen=offered[0]
            return ManualControllerAdapter(lambda _: (chosen.candidate_id,())).choose_primary_action(context)
        def __getattr__(self,name):
            return getattr(real,name)
    c.controller=Controller()
    c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    resolve(lambda a:t.auto_step(m,t.state(m)['last_sequence'],a))
    e=reload(c,m)
    helped=[v for v in e.events if v.event_type=='REACTION_RESOLVED' and v.source_definition_id==FEATHER]
    assert len(helped)==1
    assert set(helped[0].target_ids)=={LEFT,ALLY}
    for aid in (LEFT,ALLY,RIGHT):
        assert e.state.actors[aid].position.z==0
    assert any(v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids
               and v.source_definition_id=='system:combat.falling' and v.payload['reduced_to']>0 for v in e.events)
    assert not any(v.event_type=='DAMAGE_COMMITTED' and LEFT in v.target_ids
                   and v.source_definition_id=='system:combat.falling' and v.payload['reduced_to']>0 for v in e.events)


@pytest.mark.parametrize('direction,xyz', [('up',(6,6,1)),('up-northeast',(7,5,1))])
def test_wind_line_vertical_directions_use_native_physical_movement(tmp_path,direction,xyz):
    def setup(bundle):
        bow_edit()(bundle)
        if bundle['actor_id']==RIGHT:
            bundle['actor_template']['fly_speed_ft']=30
    c,t,m=fight(tmp_path,[GATHER,WIND_LINE],left_kit=BOW,bundle_edit=setup,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':6,'y':6}})
    resolve(cell_send(t,m,'Gather Current: Carry',(5,6)),
        {'choice:needle.wind_line_direction':[direction]})
    resolve(lambda a:act(t,m,bow_name(t,m),a,target_id=RIGHT))
    e=reload(c,m)
    p=e.state.actors[RIGHT].position
    assert (p.x,p.y,p.z)==xyz
    assert any(v.event_type=='MOVEMENT_COMMITTED' and v.source_definition_id==WIND_LINE
        and v.payload['destination']['z']==1 for v in e.events)


def test_wind_line_updraft_retains_its_printed_upward_direction(tmp_path):
    c,t,m=fight(tmp_path,['TAL_AIR_UPDRAFT_GATE',WIND_LINE],
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':8,'y':6}})
    _,prompts=resolve(cell_send(t,m,'Updraft Gate',(7,6)))
    e=reload(c,m)
    assert any(z.active and z.trigger_profile.get(DIRECTION)==[0,0,1] for z in e.state.zones.values())
    assert not any(q['context']['reaction_source_id']=='choice:needle.wind_line_direction' for q in prompts)


@pytest.mark.parametrize('restriction,decline', [
    ('difficult', False), ('difficult', True),
    ('frightened', False), ('frightened', True), ('disabled', True)])
def test_cloud_step_offers_only_native_legal_drift_and_can_land(tmp_path, restriction, decline):
    def setup(bundle):
        if bundle['actor_id'] != LEFT:
            return
        if restriction == 'difficult':
            add_action(bundle, 'Difficult air', [{'type': 'zone'}], target='SELF', typed={
                'zone_spec': {'name': 'Difficult air', 'shape': 'cube', 'size_ft': 30,
                              'centered_on_self': True, 'difficult': 'all',
                              'duration': {'kind': 'until_removed'}}})
        else:
            add_action(bundle, 'Restrict drift', [{'type': 'condition',
                'condition': 'frightened' if restriction == 'frightened' else 'test_grounded',
                'applies_to': 'self', 'duration': {'kind': 'until_removed'},
                'condition_data': {'avoid': RIGHT} if restriction == 'frightened' else {'flight_disabled': 1}}],
                target='SELF')
    c,t,m = fight(tmp_path, [GATHER,WIND_BODY,FEATHER,CLOUD_STEP], bundle_edit=setup,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':8,'y':6}})
    resolve(cell_send(t,m,'Gather Current: Carry',(3,6)))
    resolve(move_to(c,t,m,(3,6,2)))
    if restriction != 'disabled':
        resolve(lambda a:act(t,m,'Difficult air' if restriction == 'difficult' else 'Restrict drift',a))
    before = reload(c,m).state.model_dump(mode='json')
    def send(answers):
        result = act(t,m,'Restrict drift' if restriction == 'disabled' else 'end',answers)
        if result['status'] == 'REACTION_REQUIRED':
            assert reload(c,m).state.model_dump(mode='json') == before
        return result
    chosen = [] if decline else ['drift:4,6' if restriction == 'difficult' else 'drift:2,6']
    _,prompts = resolve(send, {'choice:needle.cloud_step_delay':[], 'choice:needle.cloud_step_drift':chosen})
    drift = [p for p in prompts if p['context']['reaction_source_id']=='choice:needle.cloud_step_drift']
    if restriction == 'disabled':
        assert not drift
    else:
        assert drift
        ids = {o['id'] for o in drift[-1]['choice']['options']}
        assert 'drift:5,6' not in ids  # too costly, or closer to the visible fear source
        assert ('drift:4,6' if restriction == 'difficult' else 'drift:2,6') in ids
    e = reload(c,m)
    actor = e.state.actors[LEFT]
    assert actor.position.z == 0
    assert actor.position.x == (3 if decline else 4 if restriction == 'difficult' else 2)
    assert not any(h.condition_id.endswith('cloud_step_drift') for h in actor.conditions.values())
    assert actor.current_hp == 1000
    if not decline:
        receipt = next(v for v in reversed(e.events) if v.event_type=='MOVEMENT_COMMITTED'
                       and v.source_definition_id==CLOUD_STEP)
        assert receipt.payload['granted_cost_ft'] == (10 if restriction == 'difficult' else 5)


@pytest.mark.parametrize('dc,designated,expected', [(100,False,0),(-100,False,2),(100,True,2)])
def test_falling_arrival_on_sky_road_runs_entry_save_and_continues_descent(tmp_path, dc, designated, expected):
    def setup(bundle):
        road_setup(bundle)
        add_action(bundle, 'Restore flight', [{'type':'remove_condition',
            'condition':name, 'applies_to':'self'} for name in ('test_grounded','prone')], target='SELF')
    c,t,m = fight(tmp_path,[SKY_ROAD],bundle_edit=setup,left_save_dc=dc,
        positions={LEFT:{'x':3,'y':6,'z':2},RIGHT:{'x':6,'y':6,'z':6}})
    cast_road(c,t,m,{'choice:needle.sky_road_designated':[RIGHT] if designated else []})
    turn(t,m,RIGHT)
    resolve(lambda a:act(t,m,'Ground flight',a))
    e=reload(c,m)
    assert e.state.actors[RIGHT].position.z == expected
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT]
    assert len(saves) == (0 if designated else 1)
    falls=[v for v in e.events if v.event_type=='MOVEMENT_COMMITTED'
           and v.actor_id==RIGHT and v.source_definition_id=='system:combat.falling']
    assert sum(v.payload['fall_distance_ft'] for v in falls) == (6-expected)*5
    damage=[v for v in e.events if v.event_type=='DAMAGE_ROLLED'
            and v.actor_id==RIGHT and v.source_definition_id=='system:combat.falling']
    assert len(damage)==1  # a rejected intermediate support does not split the damage packet
    assert len(damage[0].payload['dice']) == (6-expected)//2

    if not designated and expected == 2:
        # A second arrival on the same turn uses the native zone receipt.
        resolve(lambda a:act(t,m,'Restore flight',a))
        resolve(move_to(c,t,m,(6,6,4)))
        resolve(lambda a:act(t,m,'Ground flight',a))
        e=reload(c,m)
        assert e.state.actors[RIGHT].position.z == 2
        assert len([v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT]) == 1


def test_falling_arrival_choice_rolls_back_movement_and_road_save(tmp_path):
    empress = 'TAL_FATE_EMPRESS_OF_HIDDEN_GROWTH_AUSPICE'
    c,t,m=fight(tmp_path,[SKY_ROAD],right_talents=[empress],bundle_edit=road_setup,left_save_dc=100,
        right_team='team:factory', extra_witness=True,
        positions={LEFT:{'x':3,'y':6,'z':2},RIGHT:{'x':6,'y':6,'z':6}})
    cast_road(c,t,m,{'choice:needle.sky_road_designated':[]})
    turn(t,m,RIGHT)
    resolve(lambda a:act(t,m,'Empress of Hidden Growth Auspice',a,target_id=RIGHT))
    before=reload(c,m).state.model_dump(mode='json')
    road_source=next(z.source_definition_id for z in reload(c,m).state.zones.values() if z.active)
    def send(answers):
        result=act(t,m,'Ground flight',answers)
        if result['status']=='REACTION_REQUIRED':
            assert reload(c,m).state.model_dump(mode='json') == before
        return result
    _,prompts=resolve(send,{'choice:needle.empress_release':[]})
    assert any(p['context']['reaction_source_id']=='choice:needle.empress_release'
               and 'Sky Road' in str(p) for p in prompts)
    e=reload(c,m)
    assert e.state.actors[RIGHT].position.z == 0
    assert len([v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT
                and v.source_definition_id==road_source]) == 1
