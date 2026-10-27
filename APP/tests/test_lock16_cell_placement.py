"""Chosen-square summoning through native menus, controller, commit and reload."""
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position, ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat import cell_placement
from tests.test_summons import _sheet, ROOT, OWNER, AN
from tests.test_hidden_targeting import turn


def fight(tmp_path, *, large=False, opted=True, seed='LOCK16-CELL', owner_at=(3,6), foe_at=(12,6), reaction=False):
    bundle=compile_character(_sheet(['tianxia.talent.ink.painted_beast']),actor_id=OWNER)
    for row in bundle['action_catalog']:
        if row['parameters'].get('summon_group'):
            if opted:
                row.update(target_kind='CELL',range_ft=30)
                row['parameters']['cell_placement']={}
                row['parameters']['typed']['range_ft']=30
    if large:
        for row in bundle['summons']: row['summon']['size']='large'
    bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    bundles=[bundle]
    if reaction:
        # A bound synthetic reaction isolates the placement checkpoint from
        # unrelated printed-trigger parsing. It executes through the real
        # reaction window, movement events and Table transaction.
        reactor=compile_character(_sheet([]),actor_id=AN)
        reactor['typed_reactions'].append({'feature_id':'TEST_CELL_REACTION',
            'name':'Close on the summoner','block':'generic','kind':'technique_used',
            'range_ft':30,'costs':[],'numbers':{'cl':10,'pb':4},
            'effects':[{'type':'reaction_move','direction':'toward','distance_ft':5}]})
        reactor.pop('bundle_sha256',None);reactor['bundle_sha256']=canonical_sha256(reactor)
        bundles.append(reactor)
    combat=CombatService(ROOT,tmp_path)
    mid=combat.persistence.create_match(match_seed=seed,typed_bundles=tuple(bundles),roster_setup={
        'primary_actor_ids':[OWNER,AN], 'team_by_actor':{OWNER:'a',AN:'b'},
        'starting_positions':{OWNER:{'x':owner_at[0],'y':owner_at[1]},AN:{'x':foe_at[0],'y':foe_at[1]}}}).match_id
    for aid in (OWNER,AN):combat.set_controller_mode(mid,actor_id=aid,controller_mode='MANUAL')
    table=TabletopService(combat,tmp_path);turn(table,mid,OWNER)
    return combat,table,mid


def placements(engine):
    return [c for c in engine.legal_candidates() if c.metadata.get('cell_placement')]


@pytest.mark.parametrize('large',[False,True])
@pytest.mark.parametrize('auto',[False,True])
def test_exact_chosen_square_commit_reload_replay(tmp_path,large,auto):
    combat,table,mid=fight(tmp_path,large=large)
    engine=combat._load_session(mid).engine
    choices=placements(engine)
    assert len(choices)>1 and all(not c.target_ids for c in choices)
    before=engine.state.model_dump(mode='json')
    if large:
        assert not any(c.destination==Position(x=11,y=6) for c in choices)
        assert not any(c.destination.x==engine.grid.width-1 for c in choices)
    if auto:
        combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
        from combat.gate4_context import build_decision_context
        policy,_=combat.policies.for_actor(OWNER)
        ctx=build_decision_context(engine,policy,for_ai=True)
        choice=combat.controller.choose_primary_action(ctx)
        selected=next(c for c in ctx.legal_candidates if c.candidate_id==choice.intent.candidate_id)
        assert selected.metadata.get('cell_placement')
        result=table.auto_step(mid,0,[])
    else:
        selected=next(c for c in choices if c.destination==Position(x=7,y=6))
        table.state(mid)
        assert engine.state.model_dump(mode='json')==before
        result=table.act(mid,selected.candidate_id,selected.decision_id,selected.state_version,0,[])
    assert result['status']=='COMMITTED',result
    fresh=CombatService(ROOT,tmp_path)._load_session(mid)
    appeared=next(e for e in fresh.engine.events if e.event_type=='SUMMON_APPEARED')
    creature=fresh.engine.state.actors[appeared.target_ids[0]]
    assert creature.position==selected.destination
    assert len(fresh.engine._actor_cells(creature))==(4 if large else 1)
    assert appeared.payload['position']==selected.destination.model_dump(mode='json')
    assert any(e.payload.get('placement')==appeared.payload['position'] for e in fresh.engine.events)
    assert fresh.engine.state==combat._load_session(mid).engine.state
    assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'


def test_generic_object_or_terrain_square_validation_is_pure(tmp_path):
    combat,_,mid=fight(tmp_path)
    e=combat._load_session(mid).engine;a=e.state.actors[OWNER]
    action=ActionDefinition(source_definition_id='test:place',display_name='Place a barrier',owner_id=OWNER,
        economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='CELL',range_ft=30,
        parameters={'cell_placement':{'width_cells':2,'height_cells':2},'typed':{'effects':[]}})
    before=e.state.model_dump(mode='json')
    assert cell_placement.legal(e,a,action,Position(x=7,y=6))
    assert not cell_placement.legal(e,a,action,a.position)
    assert not cell_placement.legal(e,a,action,Position(x=10,y=6))
    assert not cell_placement.legal(e,a,action,Position(x=e.grid.width-1,y=6))
    e.grid.blocked.add((8,6))
    assert not cell_placement.legal(e,a,action,Position(x=7,y=6))
    assert e.state.model_dump(mode='json')==before


def test_legacy_self_bundle_keeps_footprint_after_loading_large_same_identity(tmp_path):
    old,table,mid=fight(tmp_path/'old',opted=False)
    old_engine=old._load_session(mid).engine
    assert not placements(old_engine)
    summon=next(c for c in old_engine.legal_candidates()
                if old_engine.action_catalog.get(c.source_definition_id)
                and old_engine.action_catalog[c.source_definition_id].parameters.get('summon_group'))
    assert summon.destination is None and summon.target_ids==(OWNER,)
    fresh,_,new_mid=fight(tmp_path/'new',large=True)
    new_creature=next(a for a in fresh._load_session(new_mid).engine.state.actors.values() if a.summon)
    assert len(fresh._load_session(new_mid).engine._actor_cells(new_creature))==4
    loaded=CombatService(ROOT,tmp_path/'old')._load_session(mid)
    old_creature=next(a for a in loaded.engine.state.actors.values() if a.summon)
    assert len(loaded.engine._actor_cells(old_creature))==1
    result=table.act(mid,summon.candidate_id,summon.decision_id,summon.state_version,0,[])
    assert result['status']=='COMMITTED'
    assert CombatService(ROOT,tmp_path/'old')._load_session(mid).mechanical.replay()['status']=='PASS'


def test_large_self_summon_automatic_anchor_checks_whole_body(tmp_path):
    # Nearest free anchor toward the foe is (19,5), but its 2x2 body would
    # overlap the foe and extend past the right edge of this 20-cell map.
    combat,table,mid=fight(tmp_path,large=True,opted=False,owner_at=(18,6),foe_at=(19,6))
    e=combat._load_session(mid).engine
    choice=next(c for c in e.legal_candidates() if c.source_definition_id in e.action_catalog
                and e.action_catalog[c.source_definition_id].parameters.get('summon_group'))
    assert table.act(mid,choice.candidate_id,choice.decision_id,choice.state_version,0,[])['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    creature=next(a for a in loaded.engine.state.actors.values() if a.summon)
    cells=set(loaded.engine._actor_cells(creature))
    assert len(cells)==4 and all(loaded.engine.grid.in_bounds(c) for c in cells)
    assert not any(cells.intersection(loaded.engine._actor_cells(a))
                   for a in loaded.engine.state.actors.values() if a.active and a is not creature)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_cell_menu_does_not_reveal_hidden_occupancy_and_execution_rechecks(tmp_path,monkeypatch):
    from combat import ext
    ext.effects()
    def conceal(engine,kind,kwargs):
        if kind=='TURN_STARTED' and OWNER in engine.state.actors:
            other=engine.state.actors[AN]
            if not any(c.condition_id=='condition:typed.invisible' for c in other.conditions.values()):
                engine._apply_condition(other,'condition:typed.invisible','test:conceal',AN,
                                        expires_on='UNTIL_REMOVED')
    monkeypatch.setitem(ext._HOOKS,'event',[*ext._HOOKS.get('event',[]),conceal])
    options=[]
    for i,at in enumerate(((7,6),(8,6))):
        combat,table,mid=fight(tmp_path/str(i),foe_at=at)
        state=table.state(mid)
        e=combat._load_session(mid).engine
        from combat.target_knowledge import knowledge
        known=knowledge(e,e.state.actors[OWNER],e.state.actors[AN])
        assert known is None or known.mode=='LAST_OBSERVED'
        options.append({(c.destination.x,c.destination.y) for c in placements(e)})
        selected=next(c for c in placements(e) if c.destination==Position(x=at[0],y=at[1]))
        result=table.act(mid,selected.candidate_id,selected.decision_id,selected.state_version,state['last_sequence'],[])
        assert result['status']=='COMMITTED',result
        loaded=CombatService(ROOT,tmp_path/str(i))._load_session(mid)
        assert not any(a.active for a in loaded.engine.state.actors.values() if a.summon)
        assert any('chosen space is unavailable' in e.payload.get('log','') for e in loaded.engine.events)
        assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    assert options[0]==options[1]


def test_reaction_can_occupy_accepted_cell_before_summon_commits(tmp_path):
    combat,table,mid=fight(tmp_path,foe_at=(8,6),reaction=True)
    combat.set_controller_mode(mid,actor_id=AN,controller_mode='LOCAL_AUTO')
    e=combat._load_session(mid).engine
    assert any(row.get('kind')=='technique_used' for row in e.typed_reaction_rows[AN])
    selected=next(c for c in placements(e) if c.destination==Position(x=7,y=5))
    result=table.act(mid,selected.candidate_id,selected.decision_id,selected.state_version,0,[])
    assert result['status']=='COMMITTED',result
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[AN].position==selected.destination
    assert any(e.event_type=='REACTION_RESOLVED' for e in loaded.engine.events)
    assert not any(a.active for a in loaded.engine.state.actors.values() if a.summon)
    assert not loaded.engine.state.actors[OWNER].action_available
    assert any('chosen space is unavailable' in e.payload.get('log','') for e in loaded.engine.events)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
