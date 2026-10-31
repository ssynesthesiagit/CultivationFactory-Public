"""Verdant second pass through service commits and cold mechanical replay."""
from copy import deepcopy
import pytest
from combat.canonical import canonical_sha256
from combat.ext import verdant_chassis as verdant
from combat.ext.clearable_growth import CLEAR
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, prompt_turn

SOW = 'TAL_VERDANT_GROWTH_SOW_LIVING_CLAIM'
SEED = 'TAL_VERDANT_GROWTH_SEED_THORN_STRIKE'
OVER = 'TAL_VERDANT_GROWTH_CULTIVATED_OVERGROWTH'
SPROUT = 'TAL_VERDANT_GROWTH_MEDICINAL_SPROUT'


def setup_actions(bundles):
    for bundle in bundles:
        base = next(a for a in bundle['action_catalog'] if a['parameters'].get('typed'))
        for name, effects in [
            ('Mark ally', [{'type': 'mark', 'mark': 'Growth Mark', 'applies_to': 'target'}]),
            ('Save probe', [{'type': 'save', 'ability': 'CON', 'on_fail': [], 'on_success': []}]),
        ]:
            a = deepcopy(base)
            source = 'test:a2verdant.' + bundle['actor_id'] + '.' + name.replace(' ', '_')
            a.update(source_definition_id=source, display_name=name, economy='NONE',
                     target_kind='ALLY_OR_SELF' if name == 'Mark ally' else 'ANY_CREATURE', range_ft=60)
            a['parameters']['typed'].update(source=source, effects=effects, range_ft=60, riders=[], area=None)
            bundle['action_catalog'].append(a)
            bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('clearing_actor', [OWNER, ALLY, FOE])
def test_overgrowth_clear_one_square_and_reload(tmp_path, clearing_actor):
    combat, table, mid = fixture(tmp_path, [SOW, OVER], positions={
        OWNER: {'x':3,'y':6}, ALLY: {'x':4,'y':6}, FOE: {'x':6,'y':6}})
    settle(table, mid, candidate(combat, mid, 'Cultivated Overgrowth', at=(5,6)).candidate_id)
    before = reload(tmp_path, mid)
    zone, = [z for z in before.state.zones.values() if z.active]
    assert zone.trigger_profile['profile']['clear_square_action'] == 1
    cells = {(p.x,p.y) for p in zone.affected_cells}
    from combat import zones
    assert (6,6) in zones.difficult_cells(before, before.state.actors[FOE])
    assert (4,6) not in zones.difficult_cells(before, before.state.actors[ALLY])
    if clearing_actor == OWNER:
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    prompt_turn(table, mid, clearing_actor)
    engine = combat._load_session(mid).engine
    from combat.ext.clearable_growth import options
    key = next(k for k, (_, p) in options(engine, engine.state.actors[clearing_actor]).items()
               if (p.x,p.y) == (4 if clearing_actor != FOE else 6,6))
    settle(table, mid, candidate(combat, mid, 'Clear a square of growth').candidate_id,
           {'choice:needle.clear_growth':key})
    after = reload(tmp_path, mid)
    current = after.state.zones[zone.zone_id]
    removed = (4 if clearing_actor != FOE else 6,6)
    assert {(p.x,p.y) for p in current.affected_cells} == cells - {removed}
    assert current.active and current.concentration_link
    assert removed not in zones.difficult_cells(after, after.state.actors[FOE])
    # Action was paid: no second clear on this turn.
    assert not [c for c in after.legal_candidates() if c.source_definition_id == CLEAR]


def test_legacy_overgrowth_does_not_add_clear_action(tmp_path):
    def legacy(bundles):
        for b in bundles:
            for a in b['action_catalog']:
                spec = a.get('parameters',{}).get('typed',{}).get('zone_spec') or {}
                spec.pop('profile',None)
            b.pop('bundle_sha256',None); b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [SOW,OVER], bundle_transform=legacy)
    settle(table, mid, candidate(combat, mid, 'Cultivated Overgrowth', at=(5,6)).candidate_id)
    assert CLEAR not in reload(tmp_path, mid).action_catalog


@pytest.mark.parametrize('category,condition,ability,expected', [
    (None,'poisoned','CON',True), (None,'disease','CON',True),
    ('disease',None,'CON',True), ('environmental_exposure_exhaustion',None,'CON',True),
    ('ongoing_poison_damage',None,'CON',True),
    (None,'exhaustion','CON',False), (None,None,'CON',False),
    ('ongoing_poison_damage',None,'DEX',False), ('other',None,'CON',False),
])
def test_medicinal_sprout_one_relevant_save(tmp_path, category, condition, ability, expected):
    def probes(bundles):
        setup_actions(bundles)
        for b in bundles:
            a = next(a for a in b['action_catalog'] if a['display_name'] == 'Save probe')
            e = a['parameters']['typed']['effects'][0]
            e['ability'] = ability
            if category: e['save_categories'] = [category]
            if condition: e['on_fail'] = [{'type':'condition','condition':condition,'applies_to':'target'}]
            b.pop('bundle_sha256',None); b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [SOW,SEED,SPROUT], bundle_transform=probes,
        ally_talents=[SEED], foe_sheet=None)
    settle(table, mid, candidate(combat, mid, 'Sow Living Claim', at=(4,6)).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Mark ally',target=ALLY).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Verdant Response: Shelter',target=ALLY).candidate_id)
    before = reload(tmp_path,mid)
    assert any(c.condition_id == 'condition:typed.verdant_medicinal' for c in before.state.actors[ALLY].conditions.values())
    settle(table, mid, candidate(combat, mid, 'Save probe',target=ALLY).candidate_id)
    after = reload(tmp_path,mid)
    rolls = [r for r in after.rolls if r.actor_id == ALLY and 'SAVE' in str(r.reason)]
    assert rolls
    assert (rolls[-1].mode == 'ADVANTAGE') == expected
    remaining = any(c.condition_id == 'condition:typed.verdant_medicinal' for c in after.state.actors[ALLY].conditions.values())
    assert remaining != expected
    if expected:
        settle(table, mid, candidate(combat, mid, 'Save probe',target=ALLY).candidate_id)
        after = reload(tmp_path,mid)
        rolls = [r for r in after.rolls if r.actor_id == ALLY and 'SAVE' in str(r.reason)]
        assert rolls[-1].mode != 'ADVANTAGE'


def test_ai_overgrowth_hinders_and_marks_only_enemies(tmp_path):
    from tests.r1i_service_support import force_ai_candidate
    combat, table, mid = fixture(tmp_path,[SOW,OVER], positions={
        OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':6,'y':6}})
    cid = candidate(combat,mid,'Cultivated Overgrowth',at=(5,6)).candidate_id
    force_ai_candidate(combat,mid,OWNER,cid)
    settle(table,mid,cid,auto=True)
    engine = reload(tmp_path,mid)
    from combat import zones
    assert (6,6) in zones.difficult_cells(engine,engine.state.actors[FOE])
    assert (4,6) not in zones.difficult_cells(engine,engine.state.actors[ALLY])
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='MANUAL')
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    prompt_turn(table,mid,FOE)
    engine = reload(tmp_path,mid)
    assert verdant.marks(engine.state.actors[FOE],engine.state.actors[OWNER]) == 1
    assert verdant.marks(engine.state.actors[ALLY],engine.state.actors[OWNER]) == 0


@pytest.mark.parametrize('pick', [None,FOE])
def test_overgrowth_terrain_choice_does_not_exempt_enemy_marks(tmp_path,pick):
    combat,table,mid=fixture(tmp_path,[SOW,OVER],positions={
        OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':6,'y':6}})
    prompts=settle(table,mid,candidate(combat,mid,'Cultivated Overgrowth',at=(5,6)).candidate_id,
                   {'choice:needle.growth_terrain':pick})
    prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.growth_terrain')
    assert {o['id'] for o in prompt['choice']['options']} == {FOE}
    engine=reload(tmp_path,mid)
    from combat import zones
    assert ((6,6) in zones.difficult_cells(engine,engine.state.actors[FOE])) == (pick==FOE)
    assert (4,6) not in zones.difficult_cells(engine,engine.state.actors[ALLY])
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    prompt_turn(table,mid,FOE)
    engine=reload(tmp_path,mid)
    assert verdant.marks(engine.state.actors[FOE],engine.state.actors[OWNER]) == 1
    assert not verdant.marks(engine.state.actors[ALLY],engine.state.actors[OWNER])


@pytest.mark.parametrize('condition', ['poisoned','disease'])
def test_medicinal_sprout_native_repeat_save(tmp_path,condition):
    def probes(bundles):
        setup_actions(bundles)
        owner=next(b for b in bundles if b['actor_id']==OWNER)
        base=next(a for a in owner['action_catalog'] if a['display_name']=='Mark ally')
        a=deepcopy(base);a.update(source_definition_id='test:a2verdant.affliction',display_name='Affliction setup')
        a['parameters']['typed'].update(source='test:a2verdant.affliction',numbers={**a['parameters']['typed']['numbers'],'save_dc':99},
            effects=[{'type':'condition','condition':condition,'applies_to':'target','duration':'one_minute',
                      'repeat_save':{'ability':'CON','when':'end'}}])
        owner['action_catalog'].append(a);owner['actor_template']['action_ids'].append(a['source_definition_id'])
        owner.pop('bundle_sha256',None);owner['bundle_sha256']=canonical_sha256(owner)
    combat,table,mid=fixture(tmp_path,[SOW,SEED,SPROUT],bundle_transform=probes)
    settle(table,mid,candidate(combat,mid,'Affliction setup',target=ALLY).candidate_id)
    settle(table,mid,candidate(combat,mid,'Sow Living Claim',at=(4,6)).candidate_id)
    settle(table,mid,candidate(combat,mid,'Mark ally',target=ALLY).candidate_id)
    settle(table,mid,candidate(combat,mid,'Verdant Response: Shelter',target=ALLY).candidate_id)
    reload(tmp_path,mid)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    prompt_turn(table,mid,ALLY)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    engine=reload(tmp_path,mid)
    rows=[r for r in engine.rolls if r.actor_id==ALLY and r.reason=='SAVE:test:a2verdant.affliction:CON']
    assert rows and rows[-1].mode=='ADVANTAGE'
    assert not any(c.condition_id=='condition:typed.verdant_medicinal' for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('kind',['caster','nested'])
def test_medicinal_sprout_ignores_unrelated_recipient_and_nested_saves(tmp_path,kind):
    def probes(bundles):
        setup_actions(bundles)
        for b in bundles:
            a=next(a for a in b['action_catalog'] if a['display_name']=='Save probe')
            outer=a['parameters']['typed']['effects'][0]
            outer['ability']='CON'
            if kind=='caster':
                outer['on_fail']=[{'type':'condition','condition':'poisoned','applies_to':'self'}]
            else:
                # Poisoned is an outcome of a separate nested DEX save, not this CON save.
                outer['on_fail']=[{'type':'save','ability':'DEX','on_fail':[
                    {'type':'condition','condition':'poisoned','applies_to':'target'}]}]
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[SOW,SEED,SPROUT],bundle_transform=probes)
    settle(table,mid,candidate(combat,mid,'Sow Living Claim',at=(4,6)).candidate_id)
    settle(table,mid,candidate(combat,mid,'Mark ally',target=ALLY).candidate_id)
    settle(table,mid,candidate(combat,mid,'Verdant Response: Shelter',target=ALLY).candidate_id)
    settle(table,mid,candidate(combat,mid,'Save probe',target=ALLY).candidate_id)
    engine=reload(tmp_path,mid)
    rows=[r for r in engine.rolls if r.actor_id==ALLY and r.reason.endswith(':CON')]
    assert rows and rows[-1].mode!='ADVANTAGE'
    assert any(c.condition_id=='condition:typed.verdant_medicinal' for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('broken_spec', [{'profile': None}])
def test_clear_growth_tolerates_unrelated_null_zone_metadata(tmp_path, broken_spec):
    def unrelated(bundles):
        for b in bundles:
            base = deepcopy(next(a for a in b['action_catalog'] if a['parameters'].get('typed')))
            base.update(source_definition_id='test:a2verdant.null.' + b['actor_id'], display_name='Unrelated legacy action',
                        economy='NONE', target_kind='SELF')
            base['parameters']['typed'].update(effects=[], zone_spec=broken_spec, area=None,
                                              source=base['source_definition_id'])
            b['action_catalog'].insert(0,base)
            b['actor_template']['action_ids'].append(base['source_definition_id'])
            b.pop('bundle_sha256',None); b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[SOW,OVER],bundle_transform=unrelated)
    settle(table,mid,candidate(combat,mid,'Cultivated Overgrowth',at=(5,6)).candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    prompt_turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    from combat.ext.clearable_growth import options
    key=next(iter(options(engine,engine.state.actors[OWNER])))
    zone,cell=options(engine,engine.state.actors[OWNER])[key]
    before=len(zone.affected_cells)
    settle(table,mid,candidate(combat,mid,'Clear a square of growth').candidate_id,
           {'choice:needle.clear_growth':key})
    after=reload(tmp_path,mid).state.zones[zone.zone_id]
    assert len(after.affected_cells)==before-1
    assert (cell.x,cell.y) not in {(p.x,p.y) for p in after.affected_cells}


@pytest.mark.parametrize('hidden', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
def test_forest_ai_uses_only_perceived_arrival_with_both_sides_in_range(tmp_path, hidden, legacy):
    from tests.r1i_service_support import fixture as forest_fixture, candidate as forest_candidate, OWNER as O, FOE as F, SECOND
    from tests.test_c16_forest_choices import actions, FOREST, move_candidate
    from tests.test_r1i_round3 import reload as forest_reload, resolve
    from tests.test_riders_c16 import SOWN, SEED as FOREST_SEED, growth
    def probes(bundles):
        actions(bundles)
        for b in bundles:
            if legacy:
                for row in b.get('typed_passives',[]):row.pop('perceived_response',None)
            if b['actor_id']==F:
                a=deepcopy(next(a for a in b['action_catalog'] if a['display_name']=='Self mark'))
                a.update(source_definition_id='test:a2verdant.invisibility',display_name='Become invisible')
                a['parameters']['typed'].update(effects=[{'type':'condition','condition':'invisible',
                                                        'duration':'one_minute','applies_to':'self'}])
                b['action_catalog'].append(a);b['actor_template']['action_ids'].append(a['source_definition_id'])
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid,send,commit=forest_fixture(tmp_path,[SOWN,FOREST_SEED,FOREST],foe_talents=[FOREST_SEED],
        bundle_transform=probes,allies=(SECOND,),positions={O:{'x':1,'y':6},F:{'x':4,'y':6},SECOND:{'x':7,'y':6}})
    commit(forest_candidate(table,mid,'Mark probe',F));commit(forest_candidate(table,mid,'Mark probe',F))
    commit(table.state(mid)['menu']['end_turn'])
    if hidden:commit(forest_candidate(table,mid,'Become invisible'))
    combat.set_controller_mode(mid,actor_id=O,controller_mode='LOCAL_AUTO')
    engine=forest_reload(tmp_path,mid)
    row=verdant.row(engine,engine.state.actors[O],'forest_remembers')
    assert (row.get('perceived_response')==1) != legacy
    _,prompts=resolve(combat,mid,send,move_candidate(table,mid,{'x':5,'y':7}),{})
    assert not prompts
    engine=forest_reload(tmp_path,mid)
    applies=not hidden or legacy
    assert growth(engine,F,O)==2-int(applies)
    made=verdant.claims(engine,engine.state.actors[O])
    assert len(made)==int(applies)
    if made:assert (made[0].position.x,made[0].position.y)==(5,7)
    assert growth(engine,SECOND,O)==0


@pytest.mark.parametrize('legacy', [False, True])
def test_forest_ai_declines_unobserved_trigger_from_arrival_outside_range(tmp_path,legacy):
    from tests.r1i_service_support import fixture as forest_fixture, candidate as forest_candidate, OWNER as O, FOE as F, SECOND
    from tests.test_c16_forest_choices import actions, FOREST, CHOICE, move_candidate
    from tests.test_r1i_round3 import reload as forest_reload, resolve
    from tests.test_riders_c16 import SOWN, SEED as FOREST_SEED, growth
    def probes(bundles):
        actions(bundles)
        if legacy:
            for b in bundles:
                for row in b.get('typed_passives',[]):row.pop('perceived_response',None)
                b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid,send,commit=forest_fixture(tmp_path,[SOWN,FOREST_SEED,FOREST],foe_talents=[FOREST_SEED],
        bundle_transform=probes,allies=(SECOND,),positions={O:{'x':0,'y':0},F:{'x':11,'y':0},SECOND:{'x':0,'y':6}})
    commit(forest_candidate(table,mid,'Mark probe',F));commit(forest_candidate(table,mid,'Mark probe',F))
    commit(table.state(mid)['menu']['end_turn'])
    combat.set_controller_mode(mid,actor_id=O,controller_mode='LOCAL_AUTO')
    _,prompts=resolve(combat,mid,send,move_candidate(table,mid,{'x':18,'y':0},teleport=True),
                     {'choice:needle.teleport_destination':'cell:18,0'})
    assert not [p for p in prompts if p['context']['reaction_source_id']==CHOICE]
    engine=forest_reload(tmp_path,mid)
    from combat.target_knowledge import can_see
    assert can_see(engine,engine.state.actors[O],engine.state.actors[F])
    assert growth(engine,F,O)==2-int(legacy)
    made=verdant.claims(engine,engine.state.actors[O])
    assert len(made)==int(legacy)
    if made:assert (made[0].position.x,made[0].position.y)==(18,0)
