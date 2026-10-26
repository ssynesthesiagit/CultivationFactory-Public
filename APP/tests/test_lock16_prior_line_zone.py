"""Current line-zone shading, membership and damage remain consistent after reload."""
import json

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act


def create_line_zone_fight(source, data):
    from combat.factory_compiler import compile_character
    from combat.canonical import canonical_sha256
    from combat.gate2_runtime_content import AN
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
    from tests.h1_support import sheet
    from tests.test_hidden_targeting import turn
    owner='actor:factory.prior-line'
    bundle=compile_character(sheet([],cl=10),actor_id=owner)
    area={'shape':'line','size_ft':60,'width_ft':5}
    action=ActionDefinition(source_definition_id='test:prior-line',display_name='Practice line',owner_id=owner,
        economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='CELL',range_ft=60,
        parameters={'typed':{'numbers':{'pb':4,'cl':10},'area':area,'effects':[],
            'zone_spec':{**area,'name':'Practice line','duration':{'kind':'minute'},'triggers':[
                {'id':'test:line-start','name':'Practice line','on':['start'],'who':'any',
                 'effects':[{'type':'damage','flat':1,'damage_types':['force']}]}]}}})
    bundle['action_catalog'].append(action.model_dump(mode='json'))
    bundle['actor_template']['action_ids'].append(action.source_definition_id)
    bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    arena=json.loads((source/'combat/rules/arenas/Pillar_Arena.json').read_text())
    arena.pop('retired', None)  # Listing metadata is not battlefield simulation data.
    arena['terrain_regions']=[{'terrain_type':'BLOCKED','movement_cost':1,'cells':[{'x':7,'y':4}]}]
    svc=CombatService(source,data)
    session=svc.persistence.create_match(match_seed='LOCK16-PRIOR-LINE',typed_bundles=(bundle,),battlefield=arena,
        roster_setup={'primary_actor_ids':[owner,AN],'team_by_actor':{owner:'a',AN:'b'},
            'starting_positions':{owner:{'x':3,'y':5},AN:{'x':11,'y':4}}})
    mid=session.match_id
    for aid in (owner,AN):svc.set_controller_mode(mid,actor_id=aid,controller_mode='MANUAL')
    table=TabletopService(svc,data);turn(table,mid,owner)
    e=svc._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.source_definition_id==action.source_definition_id and c.destination==Position(x=11,y=4))
    result=table.act(mid,c.candidate_id,c.decision_id,c.state_version,0,[])
    assert result['status']=='COMMITTED',result
    return svc, table, mid, AN


def test_line_zone_shading_membership_and_reload(tmp_path):
    data=tmp_path/'userdata'
    service, table, mid, target_id=create_line_zone_fight(ROOT,data)
    def check(svc):
        from combat.spatial_areas import zone_contains
        loaded=svc._load_session(mid);e=loaded.engine
        zone=next(iter(e.state.zones.values()));target=e.state.actors[target_id]
        assert zone.affected_cells
        assert not zone_contains(e,target,zone)
        before=e.state.model_dump(mode='json')
        shown=TabletopService(svc,data).state(mid)['presentation']
        painted=next(z for z in shown['zones'] if z['zone_id']==zone.zone_id)
        assert not any((c['x'],c['y'])==(11,4) for c in painted['affected_cells'])
        assert e.state.model_dump(mode='json')==before
        return target.current_hp
    hp=check(service)
    assert act(table,mid,'end')['status']=='COMMITTED'
    fresh=CombatService(ROOT,data)
    assert check(fresh)==hp
    loaded=fresh._load_session(mid)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
