"""Crimson Court's complete clauses through table/session commits and cold replay."""
import pytest
from combat.ext.blood_court import SENSED
from tests.auto_worker1_support import fight, LEFT, RIGHT, ALLY, act, resolve, turn, reload
from tests.hunt15_support import action_sender

COURT='tianxia.talent.blood.crimson_court'
THREAD='BLOOD_BASE_BLOOD_THREAD'
SPHERE='tianxia.sphere.blood'
QI='resource:core.qi'
INVISIBLE={'type':'condition','condition':'invisible','applies_to':'self','duration':{'kind':'until_removed'}}


def table_fight(tmp_path, *, cause=(), prepare=(), **kwargs):
    return fight(tmp_path,[COURT,THREAD],spheres=[SPHERE],ally=[],cause=list(cause),prepare=list(prepare),
                 cause_target='ANY_CREATURE',prepare_target='ANY_CREATURE',left_attack_bonus=100,**kwargs)


def cast(combat,table,mid,ai=False):
    sender=action_sender(combat,table,mid,'Crimson Court',ai=ai)
    resolve(sender)
    engine=reload(combat,mid)
    assert engine.state.actors[LEFT].resources[QI]==93
    assert any(z.active and z.owner_id==LEFT for z in engine.state.zones.values())
    if ai:
        combat.set_controller_mode(mid,actor_id=LEFT,controller_mode='MANUAL')


@pytest.mark.parametrize('damage',[False,True])
def test_damage_inside_exposes_only_ordinary_invisibility_to_owner(tmp_path,damage):
    rows=([{'type':'damage','applies_to':'self','flat':10,'damage_types':['force']}] if damage else [])+[INVISIBLE]
    combat,table,mid=table_fight(tmp_path,cause=rows)
    cast(combat,table,mid)
    turn(table,mid,RIGHT); resolve(lambda a:act(table,mid,'Cause',a,target_id=RIGHT)); turn(table,mid,LEFT)
    engine=reload(combat,mid)
    from combat.target_knowledge import can_see
    assert can_see(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT]) == damage
    assert not can_see(engine,engine.state.actors[ALLY],engine.state.actors[RIGHT])
    assert any(c.condition_id==SENSED for c in engine.state.actors[RIGHT].conditions.values()) == damage
    if damage:
        resolve(lambda a:act(table,mid,'Blood Thread',a,target_id=RIGHT))
        assert any(e.event_type=='ATTACK_ROLLED' and e.actor_id==LEFT for e in reload(combat,mid).events)


def test_allied_inside_protection_and_ai_side_routing(tmp_path):
    combat,table,mid=table_fight(tmp_path,cause=[{'type':'damage','flat':40,'damage_types':['necrotic']}])
    cast(combat,table,mid,ai=True)
    engine=reload(combat,mid)
    from combat.ext import life_state
    from combat.zones import ZONE_EFFECT
    for aid in (LEFT,ALLY):
        assert any(c.condition_id==ZONE_EFFECT and c.data['rule'].get('damage_resistances')==['NECROTIC']
                   for c in engine.state.actors[aid].conditions.values())
        assert ('ADVANTAGE',None) in life_state._modes(engine.state.actors[aid],engine)
    assert not any(c.condition_id==ZONE_EFFECT for c in engine.state.actors[RIGHT].conditions.values())
    assert ('ADVANTAGE',None) not in life_state._modes(engine.state.actors[RIGHT],engine)
    turn(table,mid,RIGHT); resolve(lambda a:act(table,mid,'Cause',a,target_id=ALLY))
    assert reload(combat,mid).state.actors[ALLY].current_hp==980


def test_healing_bonus_once_per_recipient_turn_and_bloodied_notice(tmp_path):
    combat,table,mid=table_fight(tmp_path,cause=[{'type':'damage','flat':600,'damage_types':['force']}],
                               prepare=[{'type':'healing','applies_to':'target','flat':5}])
    cast(combat,table,mid)
    turn(table,mid,RIGHT); resolve(lambda a:act(table,mid,'Cause',a,target_id=ALLY)); turn(table,mid,LEFT)
    engine=reload(combat,mid)
    assert any('becomes Bloodied' in str(e.payload) for e in engine.events)
    for _ in range(2): resolve(lambda a:act(table,mid,'Prepare',a,target_id=ALLY))
    engine=reload(combat,mid)
    assert engine.state.actors[ALLY].current_hp==414 # 5 + PB4, then only 5
    turn(table,mid,RIGHT); turn(table,mid,LEFT)
    resolve(lambda a:act(table,mid,'Prepare',a,target_id=ALLY))
    assert reload(combat,mid).state.actors[ALLY].current_hp==423


@pytest.mark.parametrize('bloodied,blood',[(True,True),(False,True),(True,False)])
def test_save_disadvantage_requires_bloodied_enemy_and_owners_blood_source(tmp_path,bloodied,blood):
    def stamp(bundle):
        for action in bundle['action_catalog']:
            if action['display_name']=='Prepare':
                action['parameters']['typed'].update(source=THREAD if blood else 'unrelated',sphere=SPHERE if blood else 'unrelated')
    combat,table,mid=table_fight(tmp_path,cause=[{'type':'damage','applies_to':'self','flat':600 if bloodied else 10,'damage_types':['force']}],
        prepare=[{'type':'save','ability':'con','applies_to':'target','on_fail':[],'on_success':[]}],bundle_edit=stamp)
    cast(combat,table,mid)
    turn(table,mid,RIGHT); resolve(lambda a:act(table,mid,'Cause',a,target_id=RIGHT)); turn(table,mid,LEFT)
    resolve(lambda a:act(table,mid,'Prepare',a,target_id=RIGHT))
    engine=reload(combat,mid)
    save=next(r for r in reversed(engine.rolls) if str(r.reason).startswith('SAVE:'))
    assert str(save.mode)==('DISADVANTAGE' if bloodied and blood else 'NORMAL')


def test_leaving_domain_restores_invisibility_without_revealing_to_other_viewers(tmp_path):
    combat,table,mid=table_fight(tmp_path,cause=[{'type':'damage','applies_to':'self','flat':10,'damage_types':['force']},INVISIBLE])
    cast(combat,table,mid)
    turn(table,mid,RIGHT); resolve(lambda a:act(table,mid,'Cause',a,target_id=RIGHT))
    from combat.target_knowledge import can_see
    engine=reload(combat,mid)
    assert can_see(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])
    resolve(lambda a:act(table,mid,'Dash',a))
    def move(answers):
        state=table.state(mid); menu=state['menu']
        candidates=combat._load_session(mid).engine.legal_candidates()
        from combat.spatial_areas import zone_contains
        engine=combat._load_session(mid).engine
        domain=next(z for z in engine.state.zones.values() if z.active and z.owner_id==LEFT)
        candidate=next(c for c in candidates if c.kind.value=='MOVE' and c.destination is not None
                       and not c.destination.z and not zone_contains(engine,engine.state.actors[RIGHT],domain,at=c.destination))
        return table.act(mid,candidate.candidate_id,menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
    resolve(move)
    engine=reload(combat,mid)
    assert not can_see(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])
    assert any(c.condition_id=='condition:typed.invisible' for c in engine.state.actors[RIGHT].conditions.values())


def test_start_damage_and_healing_prevention_are_enemy_only(tmp_path):
    def seal(bundle):
        if bundle['actor_id']!=RIGHT: return
        sid='action:test.blood_court.recover'
        bundle['actor_template']['action_ids'].append(sid)
        bundle['action_catalog'].append({'source_definition_id':sid,'display_name':'Recover','owner_id':RIGHT,
            'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','costs':[],
            'parameters':{'typed':{'effects':[{'type':'healing','applies_to':'self','flat':50}],
                                  'numbers':{'cl':15,'pb':4,'key_mod':2},'duration':{'kind':'instant'},'riders':[]}}})
    combat,table,mid=table_fight(tmp_path,cause=[{'type':'damage','applies_to':'self','flat':600,'damage_types':['force']}],bundle_edit=seal)
    cast(combat,table,mid)
    turn(table,mid,RIGHT); resolve(lambda a:act(table,mid,'Cause',a,target_id=RIGHT)); turn(table,mid,LEFT)
    turn(table,mid,RIGHT)
    engine=reload(combat,mid)
    domain=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and '.crimson_court' in e.source_definition_id]
    assert domain and all(e.target_ids==(RIGHT,) for e in domain)
    assert engine.state.actors[LEFT].current_hp==1000 and engine.state.actors[ALLY].current_hp==1000
    hp=engine.state.actors[RIGHT].current_hp
    assert hp<400
    resolve(lambda a:act(table,mid,'Recover',a))
    assert reload(combat,mid).state.actors[RIGHT].current_hp==hp


def test_domain_ends_cleanly_when_owner_loses_concentration(tmp_path):
    rows=[{'type':'damage','applies_to':'self','flat':10,'damage_types':['force']},INVISIBLE,
          {'type':'damage','applies_to':'target','flat':1000,'damage_types':['force']}]
    combat,table,mid=table_fight(tmp_path,cause=rows)
    cast(combat,table,mid)
    turn(table,mid,RIGHT); resolve(lambda a:act(table,mid,'Cause',a,target_id=LEFT))
    engine=reload(combat,mid)
    assert not any(z.active and z.owner_id==LEFT for z in engine.state.zones.values())
    assert not any(c.condition_id==SENSED for c in engine.state.actors[RIGHT].conditions.values())
    assert any(e.event_type=='ZONE_REMOVED' for e in engine.events)


def test_damaged_hidden_enemy_stays_hidden(tmp_path):
    rows=[{'type':'damage','applies_to':'self','flat':10,'damage_types':['force']},INVISIBLE,
          {'type':'condition','condition':'hidden','applies_to':'self','duration':{'kind':'until_removed'}}]
    combat,table,mid=table_fight(tmp_path,cause=rows)
    cast(combat,table,mid)
    turn(table,mid,RIGHT); resolve(lambda a:act(table,mid,'Cause',a,target_id=RIGHT))
    engine=reload(combat,mid)
    from combat.target_knowledge import can_see
    assert not can_see(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])
    assert any(c.condition_id==SENSED for c in engine.state.actors[RIGHT].conditions.values())
