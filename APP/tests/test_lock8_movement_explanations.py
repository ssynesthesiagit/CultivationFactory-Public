"""Movement diagnostics mirror native refusals without changing legal actions."""
import pytest
from combat.gate2_runtime_models import Position
from combat import zones
from tests import lock8_support as S


def fight():
    return S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))


def snapshot(e):
    return (e.state.model_dump(mode='json'),[c.model_dump(mode='json') for c in e.legal_candidates()],
            [ev.model_dump(mode='json') for ev in e.events], [r.model_dump(mode='json') for r in e.rolls])


def test_ordinary_and_frightened_queries_are_read_only_and_directional():
    e=fight();a=e.state.actors[S.ME]
    before=snapshot(e)
    assert not e.movement_explanation(S.ME)['explained_refusal']
    assert snapshot(e)==before
    e._apply_condition(a,'condition:typed.frightened','test:fear',S.FOE,expires_on='END_OF_HOLDER_NEXT_TURN')
    before=snapshot(e)
    close=e.movement_explanation(S.ME,Position(x=4,y=6))
    away=e.movement_explanation(S.ME,Position(x=2,y=6))
    assert close['explained_refusal'] and not away['explained_refusal']
    assert close['reasons'][0]['code']=='FRIGHTENED_CLOSER'
    assert e.state.actors[S.FOE].display_name in close['reasons'][0]['message']
    assert not any(c.kind=='MOVE' and c.destination==Position(x=4,y=6) for c in e.legal_candidates())
    assert any(c.kind=='MOVE' and c.destination==Position(x=2,y=6) for c in e.legal_candidates())
    assert snapshot(e)==before


@pytest.mark.parametrize('condition,code',[('condition:core.grappled','GRAPPLED'),
 ('condition:typed.grappled','GRAPPLED'),('condition:typed.restrained','RESTRAINED'),
 ('condition:typed.pinned','SPEED_ZERO_EFFECT')])
def test_zero_speed_explains_actual_condition_and_keeps_no_moves(condition,code):
    e=fight();a=e.state.actors[S.ME]
    e._apply_condition(a,condition,'test:hold',S.FOE,expires_on='END_OF_HOLDER_NEXT_TURN',
                       data={'rule':{'speed_zero':True},'label':condition.rsplit('.',1)[-1].title()})
    before=snapshot(e);result=e.movement_explanation(S.ME,Position(x=4,y=6))
    assert result['effective_speed_ft']==0 and result['explained_refusal']
    assert code in [r['code'] for r in result['reasons']]
    assert not any(c.kind=='MOVE' for c in e.legal_candidates())
    assert snapshot(e)==before


def test_additive_speed_zero_and_hostile_terrain_cost():
    e=fight();a=e.state.actors[S.ME]
    e._add_modifier(a,'test:slow','speed_ft','ADD',-a.speed_ft,'SELF',expires_on='END_OF_HOLDER_NEXT_TURN')
    result=e.movement_explanation(S.ME)
    assert result['effective_speed_ft']==0
    assert any(r['code']=='SPEED_PENALTY' and r['delta_ft']==-a.speed_ft for r in result['reasons'])
    a.modifiers.clear()
    ctx=S.ctx_of(e,S.FOE,S.ME,S.action_id(e,S.FOE,'Scouring Hand'))
    zones.create(ctx,{'name':'Sticky ground','shape':'sphere','size_ft':10,'difficult':'hostile','duration':{}})
    before=snapshot(e);result=e.movement_explanation(S.ME,Position(x=4,y=6))
    terrain=next(r for r in result['reasons'] if r['code']=='DIFFICULT_TERRAIN')
    assert terrain['step_cost_ft']==10 and not terrain['blocks_destination']
    assert snapshot(e)==before


def test_hidden_fear_source_is_not_exposed():
    e=fight();a=e.state.actors[S.ME];b=e.state.actors[S.FOE]
    e._apply_condition(a,'condition:typed.frightened','test:fear',S.FOE,expires_on='END_OF_HOLDER_NEXT_TURN')
    e._apply_condition(b,'condition:typed.invisible','test:hide',S.FOE,expires_on='UNTIL_REMOVED')
    e.state.observations.get(a.team_id,{}).pop(S.FOE,None)
    from combat.target_knowledge import actors_for
    assert S.FOE not in {x.entity_id for x in actors_for(e,a)}
    assert not any(r['code']=='FRIGHTENED_CLOSER' for r in e.movement_explanation(S.ME)['reasons'])


@pytest.mark.parametrize('penalty', [-10, -100])
def test_hook_speed_penalty_names_real_affliction(penalty):
    from combat.ext.afflictions import condition_id
    e=fight();a=e.state.actors[S.ME]
    e._apply_condition(a,condition_id(),'test:affliction',S.FOE,expires_on='UNTIL_REMOVED',
                       data={'label':'Heavy limbs', 'speed':penalty})
    before=snapshot(e);result=e.movement_explanation(S.ME)
    assert any(r.get('delta_ft')==penalty and 'Heavy limbs' in r['message'] for r in result['reasons'])
    if penalty == -100:
        assert result['effective_speed_ft']==0
        assert 'Heavy limbs' in next(r['message'] for r in result['reasons'] if r['code']=='SPEED_ZERO')
    assert snapshot(e)==before


def test_clinch_speed_provenance():
    from combat.ext.body_iron_fist import CLINCH_SELF_CONDITION
    e=fight();a=e.state.actors[S.ME]
    e._apply_condition(a,CLINCH_SELF_CONDITION,'test:clinch',S.ME,expires_on='UNTIL_REMOVED')
    assert any(r.get('delta_ft')==-10 and 'Dragon-Step Clinch' in r['message']
               for r in e.movement_explanation(S.ME)['reasons'])


def test_terrain_uses_entered_footprint_and_higher_base_cost(monkeypatch):
    from combat.footprints import ActorFootprintDefinition
    e=fight();a=e.state.actors[S.ME];dest=Position(x=4,y=6)
    footprint=ActorFootprintDefinition.rectangle(2,2,footprint_id='test:large',source_definition_id='test:large')
    monkeypatch.setattr(e,'_footprint',lambda actor: footprint)
    monkeypatch.setattr(e,'_hostile_difficult_cells',lambda actor: {(3,6),(4,6)})
    assert not any(r['code']=='DIFFICULT_TERRAIN' for r in e.movement_explanation(S.ME,dest)['reasons'])
    e.grid.base_movement_cost[(5,6)]=3
    row=next(r for r in e.movement_explanation(S.ME,dest)['reasons'] if r['code']=='DIFFICULT_TERRAIN')
    assert row['step_cost_ft']==15 and 'Hostile' not in row['message']


def test_query_after_real_table_commit_and_reload_is_not_saved_state(monkeypatch,tmp_path):
    from combat import ext
    from combat.gate5_service import CombatService
    from tests.test_lock2_persistence import table_match,act,ROOT
    ext.effects()
    def fear(engine,event,kwargs):
        if event=='HOLD_POSITION_COMMITTED':
            actor=engine.state.actors[kwargs['actor_id']]
            other=next(a for a in engine.state.actors.values() if a.team_id!=actor.team_id)
            engine._apply_condition(actor,'condition:typed.frightened','test:fear',other.entity_id,
                                    expires_on='END_OF_HOLDER_NEXT_TURN')
    monkeypatch.setitem(ext._HOOKS,'event',[*ext._HOOKS.get('event',[]),fear])
    combat,table,mid=table_match(tmp_path)
    assert act(table,mid,'system:combat.hold_position')['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid);e=loaded.engine
    before=snapshot(e)
    result=e.movement_explanation(e.state.current_actor_id)
    assert any(r['code']=='FRIGHTENED_CLOSER' for r in result['reasons'])
    assert snapshot(e)==before
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    fresh=CombatService(ROOT,tmp_path)._load_session(mid)
    assert fresh.engine.movement_explanation(e.state.current_actor_id)==result


@pytest.mark.parametrize('base_speed', [30, 10])
def test_real_clinch_hook_names_penalty_including_zero_speed(base_speed):
    e = S.fight(S.bundle('TAL_IRON_FIST_IRON_FIST_TRAINING', 'TAL_IRON_FIST_DRAGON_STEP_CLINCH'))
    a = e.state.actors[S.ME]
    a.speed_ft = base_speed
    S.use(e, 'Dragon-Step Clinch: Maintain')
    before = snapshot(e)
    result = e.movement_explanation(S.ME)
    penalty = next(r for r in result['reasons'] if r['code'] == 'SPEED_PENALTY')
    assert penalty['delta_ft'] == -10 and 'Dragon-Step Clinch' in penalty['message']
    assert result['effective_speed_ft'] == base_speed - 10
    if base_speed == 10:
        zero = next(r for r in result['reasons'] if r['code'] == 'SPEED_ZERO')
        assert 'Dragon-Step Clinch' in zero['message']
        assert not any(c.kind == 'MOVE' for c in e.legal_candidates())
    assert snapshot(e) == before


def test_heaven_seizing_clinch_has_no_speed_penalty_or_false_source():
    e = S.fight(S.bundle('TAL_IRON_FIST_DRAGON_STEP_CLINCH', 'TAL_IRON_FIST_HEAVEN_SEIZING_CLINCH'))
    S.use(e, 'Dragon-Step Clinch: Maintain')
    before = snapshot(e)
    result = e.movement_explanation(S.ME)
    assert result['effective_speed_ft'] == 30
    assert not any(r['code'] in {'SPEED_PENALTY', 'SPEED_ZERO'} for r in result['reasons'])
    assert snapshot(e) == before


def test_affliction_hook_preserves_each_named_source_at_zero():
    from combat.ext.afflictions import condition_id
    e = fight(); a = e.state.actors[S.ME]
    a.speed_ft = 30
    for source, name, delta in [('test:slow1', 'Crippling Curse: Heavy legs', -20),
                                ('test:slow2', 'Lingering Poison: Numb legs', -10)]:
        e._apply_condition(a, condition_id(), source, S.FOE,
                           expires_on='END_OF_HOLDER_NEXT_TURN', data={'speed': delta, 'label': name})
    before = snapshot(e)
    result = e.movement_explanation(S.ME)
    assert result['effective_speed_ft'] == 0
    penalties = [r for r in result['reasons'] if r['code'] == 'SPEED_PENALTY']
    assert [(r['source_id'], r['delta_ft']) for r in penalties] == [('test:slow1', -20), ('test:slow2', -10)]
    zero = next(r for r in result['reasons'] if r['code'] == 'SPEED_ZERO')
    assert 'Crippling Curse: Heavy legs' in zero['message'] and 'Lingering Poison: Numb legs' in zero['message']
    assert snapshot(e) == before


@pytest.mark.parametrize('mount_speed', [10, 0])
def test_slow_controlled_mount_names_the_mount(mount_speed):
    from tests.test_mounts import rider_bundle, fight as mounted_fight, actors
    e = mounted_fight(rider_bundle())
    rider, mount, _ = actors(e)
    mount.speed_ft = mount_speed
    before = snapshot(e)
    result = e.movement_explanation(rider.entity_id)
    penalty = next(r for r in result['reasons'] if r['code'] == 'SPEED_PENALTY')
    assert mount.display_name in penalty['message']
    assert penalty['delta_ft'] == mount_speed - rider.speed_ft
    assert result['effective_speed_ft'] == mount_speed
    assert snapshot(e) == before


def test_trailing_large_footprint_in_zone_does_not_claim_extra_cost():
    from combat.footprints import ActorFootprintDefinition
    e = fight(); a = e.state.actors[S.ME]
    e.actor_footprints[S.ME] = ActorFootprintDefinition.rectangle(
        2, 2, footprint_id='test:large', source_definition_id='test:large')
    ctx = S.ctx_of(e, S.FOE, S.ME, S.action_id(e, S.FOE, 'Scouring Hand'))
    zones.create(ctx, {'name':'Sticky ground', 'shape':'sphere', 'size_ft':5,
                       'difficult':'all', 'duration':{}})
    destination = Position(x=4, y=6)
    difficult = e._hostile_difficult_cells(a)
    assert any(cell in difficult for cell in e.grid.footprint_cells(destination, e._footprint(a)))
    path = e.grid.shortest_path(a.position, destination, footprint=e._footprint(a), difficult_cells=difficult)
    assert path[1] == 5
    before = snapshot(e)
    assert not any(r['code'] == 'DIFFICULT_TERRAIN' for r in e.movement_explanation(S.ME, destination)['reasons'])
    assert snapshot(e) == before


@pytest.mark.parametrize('zone', [False, True])
def test_terrain_explanation_uses_grid_cost_including_higher_base_cost(zone):
    e = fight(); a = e.state.actors[S.ME]; destination = Position(x=4, y=6)
    if zone:
        ctx = S.ctx_of(e, S.FOE, S.ME, S.action_id(e, S.FOE, 'Scouring Hand'))
        zones.create(ctx, {'name':'Sticky ground', 'shape':'sphere', 'size_ft':10,
                           'difficult':'all', 'duration':{}})
    e.grid.base_movement_cost[(4, 6)] = 3
    base = e._wall_base
    e._wall_base = (*base[:3], {**base[3], (4, 6):3})
    path = e.grid.shortest_path(a.position, destination, footprint=e._footprint(a),
                                difficult_cells=e._hostile_difficult_cells(a))
    assert path[1] == 15
    before = snapshot(e)
    terrain = next(r for r in e.movement_explanation(S.ME, destination)['reasons'] if r['code'] == 'DIFFICULT_TERRAIN')
    assert terrain['step_cost_ft'] == path[1]
    assert '15 feet' in terrain['message'] and 'Hostile' not in terrain['message']
    for target in [None, Position(x=5, y=6)]:
        summary = next(r for r in e.movement_explanation(S.ME, target)['reasons'] if r['code'] == 'DIFFICULT_TERRAIN')
        assert 'step_cost_ft' not in summary
    assert snapshot(e) == before


def test_real_unimpeded_positioning_matches_native_step_and_restores_grid():
    from combat import motion
    e=S.fight(S.bundle('TAL_ATHLETICS_UNIMPEDED_POSITIONING'))
    a=e.state.actors[S.ME]; dest=Position(x=4,y=6)
    assert motion.ignores_difficult(e,a)
    e.grid.base_movement_cost[(4,6)]=3
    if getattr(e,'_wall_base',None):
        blocked,opaque,cover,cost=e._wall_base
        e._wall_base=(blocked,opaque,cover,{**cost,(4,6):3})
    before=snapshot(e)
    native=next(c for c in e.legal_candidates() if c.kind=='MOVE' and c.destination==dest)
    assert native.movement_cost_ft==5
    original=e.grid.base_movement_cost
    result=e.movement_explanation(S.ME,dest)
    assert not any(r['code']=='DIFFICULT_TERRAIN' for r in result['reasons'])
    assert e.grid.base_movement_cost is original and original[(4,6)]==3
    assert 'unimpeded_full_costs' not in e.grid.__dict__
    assert snapshot(e)==before
