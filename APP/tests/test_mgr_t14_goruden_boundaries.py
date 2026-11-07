"""Deep acquired-source timing, statue defenses and source-authority boundaries."""
import pytest
from tests.test_mgr_t14_goruden_clauses import acquired_game,use
from tests.test_mgr_t14_goruden import G
from tests.test_mgr_t14_goruden_build import settle_acquired
from tests.cw2_service_support import add_action,seal
from tests.worker2_support import OWNER,FOE,ALLY,reload,turn,candidate,settle


def test_acquired_statue_all_damage_defenses_preserve_awareness(catalog_environment,monkeypatch,tmp_path):
    kinds=('acid','bludgeoning','cold','fire','force','lightning','necrotic','piercing','radiant','slashing','thunder','poison','psychic')
    def setup(bs):
        hp=bs[0]['actor_template']['maximum_hp']
        add_action(bs[2],'All golden defenses',[
            {'type':'damage','flat':hp+hp//2,'damage_types':['force'],'applies_to':'target'},
            {'type':'healing','flat':hp,'applies_to':'target'},
            *[{'type':'damage','flat':4,'damage_types':[kind],'applies_to':'target'} for kind in kinds]])
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path,setup)
    turn(t,m,FOE)
    use(c,t,m,'All golden defenses',OWNER,{'choice:needle.goruden.immortal_gold':['survive']})
    e=reload(tmp_path,m);a=e.state.actors[OWNER]
    packets=[x.payload for x in e.events if x.event_type=='DAMAGE_COMMITTED' and OWNER in x.target_ids][-len(kinds):]
    assert [(p['damage_type'].lower(),p['reduced_to']) for p in packets]==[(k,0 if k in ('poison','psychic') else 2) for k in kinds]
    assert any(x.condition_id=='condition:typed.golden_statue' for x in a.conditions.values())
    from combat.senses import perceives
    assert perceives(e,a,e.state.actors[FOE],sight_only=True)
    from combat.typed_executor import condition_rules
    assert any(r.get('no_actions') and r.get('no_reactions') and r.get('speed_zero') for r in condition_rules(a))
    assert all(x.source_actor_id==OWNER for x in a.modifiers.values() if x.source_definition_id==G+'immortal_gold' and x.target_field in ('damage_resistance','damage_immunity'))


@pytest.mark.parametrize('source_cl,stopped',[(17,True),(18,False),(19,False)])
def test_acquired_statue_forced_movement_requires_source_cl_and_real_contest(catalog_environment,monkeypatch,tmp_path,source_cl,stopped):
    def setup(bs):
        hp=bs[0]['actor_template']['maximum_hp']
        add_action(bs[2],'Golden statue displacement',[
            {'type':'damage','flat':hp+hp//2,'damage_types':['force'],'applies_to':'target'},
            {'type':'forced_movement','applies_to':'target','distance_ft':10}],
            typed={'numbers':{'cl':source_cl,'pb':4,'key_mod':100,'save_dc':16}})
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path,setup)
    before=reload(tmp_path,m).state.actors[OWNER].position
    turn(t,m,FOE)
    use(c,t,m,'Golden statue displacement',OWNER,{'choice:needle.goruden.immortal_gold':['survive']})
    e=reload(tmp_path,m)
    assert (e.state.actors[OWNER].position==before)==stopped
    contests=[x for x in e.events if x.event_type=='CHECK_ROLLED' and x.payload.get('roll_kind')=='opposed_check']
    assert len(contests)==(0 if stopped else 1)


@pytest.mark.parametrize('restriction,factor,free_aura',[('none',0,False),('half',1,True)])
def test_acquired_statue_restoration_respects_real_healing_restrictions(catalog_environment,monkeypatch,tmp_path,restriction,factor,free_aura):
    def setup(bs):
        hp=bs[0]['actor_template']['maximum_hp']
        add_action(bs[2],'Golden restoration restriction',[
            {'type':'damage','flat':hp+hp//2,'damage_types':['force'],'applies_to':'target'},
            {'type':'healing_reduction','applies_to':'target',
             'evidence':'The target cannot regain Hit Points.' if restriction=='none' else 'Healing received is halved.',
             'expires_on':'END_OF_SOURCE_NEXT_TURN'}])
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path,setup)
    turn(t,m,FOE)
    use(c,t,m,'Golden restoration restriction',OWNER,{'choice:needle.goruden.immortal_gold':['survive']})
    spent=reload(tmp_path,m).state.actors[OWNER].resources.copy()
    turn(t,m,OWNER);e=reload(tmp_path,m);a=e.state.actors[OWNER]
    assert a.current_hp==1+(5*a.proficiency_bonus//2 if factor else 0)
    assert not any(x.condition_id=='condition:typed.golden_statue' for x in a.conditions.values())
    assert bool([z for z in e.state.zones.values() if z.active and z.owner_id==OWNER and z.source_definition_id.endswith('golden_aura')])==free_aura
    assert a.resources==spent


def test_acquired_extra_attack_chooses_radiant_per_strike_and_only_one_rider(catalog_environment,monkeypatch,tmp_path):
    def setup(bs):
        bs[2]['actor_template']['armor_class']=0;bs[2]['actor_template']['maximum_hp']=1000;seal(bs[2])
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path,setup)
    e=reload(tmp_path,m)
    action=next(a for a in e.action_catalog.values() if a.owner_id==OWNER and any(r.get('type')=='attack' and r.get('attack_kind')=='unarmed' and r.get('count',1)>1 for r in (a.parameters.get('typed') or {}).get('effects',[])))
    prompts=use(c,t,m,action.display_name,FOE,{'choice:needle.iron_fist_damage_type':['RADIANT'],
        'choice:needle.path_hit.'+G+'radiant_fist':['Extra Radiant Damage']})
    e=reload(tmp_path,m)
    choices=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.iron_fist_damage_type']
    assert len(choices)>1
    assert len([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.path_hit.'+G+'radiant_fist'])==1
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and FOE in x.target_ids]
    assert len(packets)>2 and all(x.payload.get('damage_type')=='RADIANT' for x in packets)
    assert len([x for x in packets if x.payload.get('rolled_or_pending_damage')==e.state.actors[OWNER].proficiency_bonus])>=1


def test_acquired_dead_statue_expires_at_its_nominal_next_slot_without_restoration(catalog_environment,monkeypatch,tmp_path):
    def setup(bs):
        hp=bs[0]['actor_template']['maximum_hp']
        add_action(bs[2],'Golden statue then outright death',[
            {'type':'damage','flat':hp+hp//2,'damage_types':['force'],'applies_to':'target'},
            {'type':'damage','flat':4*hp,'damage_types':['force'],'applies_to':'target'}])
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path,setup)
    turn(t,m,FOE)
    use(c,t,m,'Golden statue then outright death',OWNER,{'choice:needle.goruden.immortal_gold':['survive']})
    e=reload(tmp_path,m);a=e.state.actors[OWNER]
    assert not a.active and a.current_hp==0
    assert any(x.condition_id=='condition:typed.golden_statue' for x in a.conditions.values())
    before=e.state.event_sequence
    settle(t,m,t.state(m)['menu']['end_turn'])
    e=reload(tmp_path,m);a=e.state.actors[OWNER]
    assert not a.active and a.current_hp==0
    assert not any(x.condition_id=='condition:typed.golden_statue' or x.data.get('goruden_statue') for x in a.conditions.values())
    assert not any(x.source_definition_id==G+'immortal_gold' and x.target_field in ('damage_resistance','damage_immunity') for x in a.modifiers.values())
    assert not any(x.sequence>before and x.event_type=='HEALING_APPLIED' and x.source_definition_id==G+'immortal_gold' for x in e.events)
    assert not any(z.active and z.owner_id==OWNER and z.source_definition_id.endswith('golden_aura') for z in e.state.zones.values())
