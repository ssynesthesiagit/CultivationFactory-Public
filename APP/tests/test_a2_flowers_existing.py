"""Existing Blossom, dart and ward routes certified at service/reload boundaries."""
import pytest
from tests.hunt12_support import ME, FOE, candidate, reload, hit_dice
from tests.test_auto86_flowers import flowers_fight, shape, at, _walk, dart
from tests.test_a2_flowers import commit, end, THORN, DART, WARD


@pytest.mark.parametrize('cl,dice',[(5,'2d6'),(11,'4d6'),(17,'6d6')])
def test_thorned_field_follows_bearer_and_owns_concentration(tmp_path,cl,dice):
    combat,table,mid=flowers_fight(tmp_path,[THORN,'TAL_FLOWERS_TRAVELING_GARDEN'],cl=cl,dc=100,ask_reactions=False)
    shape(combat,table,mid,'Blossom: Thorned Bloom (2 CP)')
    commit(combat,table,mid,at(combat,mid,'Cultivate Blossom (bloom at once)',3,6))
    engine=reload(tmp_path,mid)
    zone=next(z for z in engine.state.zones.values() if z.active and (z.trigger_profile.get('placed') or {}).get('state')=='field')
    assert zone.concentration_link and zone.duration_rounds==10
    assert zone.trigger_profile['anchor_id']==ME
    assert engine.state.actors[ME].concentration is not None
    assert engine.state.actors[ME].resources['resource:core.stamina']==27
    assert _walk(combat,table,mid,3,5)
    engine=reload(tmp_path,mid)
    zone=engine.state.zones[zone.zone_id]
    assert (zone.center.x,zone.center.y)==(3,5)
    end(combat,table,mid)
    engine=reload(tmp_path,mid)
    assert any(e.event_type=='DAMAGE_ROLLED' and dice in e.payload.get('expression','') for e in engine.events)
    assert not [e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and ME in e.target_ids]


@pytest.mark.parametrize('cl,dice',[(1,'1d8'),(5,'2d8'),(11,'3d8'),(17,'4d8')])
def test_petal_dart_owner_choice_scales_and_adds_path_modifier(tmp_path,monkeypatch,cl,dice):
    combat,table,mid=flowers_fight(tmp_path,[DART],cl=cl,technique_attack_bonus=30,ask_reactions=True)
    assert _walk(combat,table,mid,2,6)
    hit_dice(monkeypatch)
    dart(combat,table,mid,answer='POISON')
    engine=reload(tmp_path,mid)
    rolled=next(e.payload for e in engine.events if e.event_type=='DAMAGE_ROLLED' and DART in e.source_definition_id)
    assert dice in rolled['expression'] and rolled['modifier']==4
    assert [e.payload['damage_type'] for e in engine.events if e.event_type=='DAMAGE_COMMITTED']==['POISON']
    assert engine.state.actors[ME].resources['resource:core.stamina']==30


@pytest.mark.parametrize('cl,dice',[(5,1),(15,2),(17,3)])
@pytest.mark.parametrize('protect_ally',[False,True])
@pytest.mark.parametrize('consume',[False,True])
def test_accepted_petal_ward_reduces_hit_and_grants_next_poison_save(tmp_path,monkeypatch,cl,dice,protect_ally,consume):
    from tests.test_tabletop_hunt6 import table_fight, LEFT, RIGHT, ALLY
    from tests.test_lock2_persistence import act
    from tests.test_carry import KIT
    from tests.r10_fixup_support import cast_sender, fixed_dice
    from tests.hunt19_support import reload as cold_reload
    combat,table,mid=table_fight(tmp_path,[WARD],cl=cl,kit={'starting_kit':KIT},ask=True,ally_talents=[])
    while table.state(mid)['menu']['actor_id']!=RIGHT: assert act(table,mid,'end')['status']=='COMMITTED'
    fixed_dice(monkeypatch,[20,20]+[4]*40)
    subject=ALLY if protect_ally else LEFT
    sender=cast_sender(combat,table,mid,'Bi Shou (Dagger) thrown',target=subject)
    answers=[]; used=False
    for _ in range(12):
        result=sender(answers)
        if result['status']=='COMMITTED':break
        prompt=result['reaction']; use=prompt['reaction']=='Petal Ward'
        used |= use
        answers.append({**prompt['context'],'selection':'USE' if use else 'DECLINE'})
    assert result['status']=='COMMITTED' and used
    engine=cold_reload(combat,tmp_path,mid)
    protected=engine.state.actors[subject]
    buff=next(c for c in protected.conditions.values() if c.condition_id=='condition:typed.save_against')
    assert buff.expires_on=='START_OF_SOURCE_NEXT_TURN'
    assert buff.data['rule']['save_against']['next'] is True
    reduced=next(e.payload for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==WARD)
    assert reduced['reduction']==min(reduced['pending_before'],dice*4+2)
    assert any(e.event_type=='RESOURCE_SPENT' and e.source_definition_id==WARD and e.payload['amount']==1 for e in engine.events)

    # The next accepted end-turn intent exercises real typed saves, after a cold
    # reload of the protected actor. Synthetic incoming effects use the shipped
    # block_save consumer; no mock supplies a mode or consumes the condition.
    from combat.typed_executor import Context, block_save
    from tests.hunt12_support import event_hook
    from tests.h1_support import script
    def saves(engine,event,kwargs):
        boundary='TURN_ENDED' if consume else 'HOLD_POSITION_COMMITTED'
        owner=RIGHT if consume else LEFT
        if event!=boundary or kwargs.get('actor_id')!=owner: return
        subject_actor=engine.state.actors[subject]
        action=next(a for a in engine.action_catalog.values() if a.owner_id==RIGHT and 'Dagger' in a.display_name)
        ctx=Context(engine,engine.state.actors[RIGHT],action,engine._active_intent,
                    {'numbers':{'save_dc':-100}},[subject_actor],subject_actor,{})
        def buff_present(): return any(c.condition_id=='condition:typed.save_against' for c in subject_actor.conditions.values())
        def save(condition):
            script(engine,[4]*40)
            block_save(ctx,{'type':'save','ability':'con','applies_to':'target',
                            'on_fail':[{'type':'condition','condition':condition,'applies_to':'target'}]})
        if consume:
            save('frightened')
            assert buff_present(), 'unrelated save consumed Ward'
            save('poisoned')
            assert not buff_present(), 'eligible save did not consume Ward'
            save('poisoned')
        else:
            assert not buff_present(), 'Ward survived caster next turn'
            save('poisoned')
    event_hook(monkeypatch,saves)
    if consume:
        assert act(table,mid,'end')['status']=='COMMITTED'
    else:
        for _ in range(4):
            if table.state(mid)['menu']['actor_id']==LEFT: break
            assert act(table,mid,'end')['status']=='COMMITTED'
        expired=cold_reload(combat,tmp_path,mid)
        assert expired.state.current_actor_id==LEFT
        assert not any(c.condition_id=='condition:typed.save_against' for c in expired.state.actors[subject].conditions.values())
        assert act(table,mid,'system:combat.hold_position')['status']=='COMMITTED'
    engine=cold_reload(combat,tmp_path,mid)
    actual=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==subject]
    assert [e.payload['mode'] for e in actual]==(['NORMAL','ADVANTAGE','NORMAL'] if consume else ['NORMAL'])
    assert all(e.payload['reason'].endswith(':CON') for e in actual)
    used=[e for e in engine.events if e.event_type=='CONDITION_REMOVED' and e.source_definition_id==WARD
          and e.payload.get('reason')=='CONSUMED']
    assert len(used)==int(consume)
