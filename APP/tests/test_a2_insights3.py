"""Printed Insight riders through CombatService, table execution and disk reload."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, reload, resolve, settle, turn, fight as service_fight

FALL='insight.fall-seven-ways'
FROZEN='insight.frozen-golden-core'
FURNACE='insight.furnace-core-survivor'
HEART='insight.furnace-heart-discipline'
STOMACH='insight.furnace-tyrant-s-stomach'
DEMON='insight.heart-demon-vanquisher'
FLESH='insight.flesh-reconstruction-insight'


def fight(tmp_path, insights=(), **kw):
    def fields(doc, aid):
        surface=doc['spheres_and_talents']; ids=surface.get('learned_talent_record_ids',[])
        surface['cultivation_insight_record_ids']=[x for x in (insights if aid==LEFT else kw.get('right_talents',())) if x.startswith('insight.')]
        surface['learned_talent_record_ids']=[x for x in ids if not x.startswith('insight.')]
    return service_fight(tmp_path, insights, sheet_edit=fields, **kw)


def typed_prepare(sphere):
    def edit(bundle):
        for a in bundle['action_catalog']:
            if a['display_name']=='Prepare':
                a['parameters']['typed'].update(sphere='tianxia.sphere.'+sphere, source='test:printed.'+sphere)
    return edit


def damage(amount, kind, who='target'):
    return {'type':'damage','flat':amount,'damage_types':[kind],'applies_to':who}


def save(rows, **kw):
    return {'type':'save','ability':'CON','on_fail':rows,'on_success':[], **kw}


def commits(c,m):
    e=reload(c,m)
    assert c.verify(m)['status']=='PASS'
    assert c.replay(m)['status']=='PASS'
    return e


@pytest.mark.parametrize('owned', [False, True])
@pytest.mark.parametrize('zero', [False, True])
def test_frozen_rider_once_per_actual_turn_and_source_next_start(tmp_path,owned,zero):
    rows=[damage(1,'cold')]
    if zero: rows.append({'type':'speed','becomes':0,'applies_to':'target','duration':{'kind':'until_start_of_next_turn'}})
    c,t,m=fight(tmp_path,[FROZEN] if owned else [],prepare=[save(rows)],bundle_edit=typed_prepare('ice'))
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=commits(c,m); victim=e.state.actors[RIGHT]
    insight_mods=[x for x in victim.modifiers.values() if x.source_definition_id==FROZEN]
    assert len(insight_mods)==int(owned)
    if owned:
        from combat.ext.passive_rows import row_of
        outcome=row_of(e,LEFT,'insights3',FROZEN)['player_outcome']
        assert 'until your next turn starts' in outcome
        assert 'until the affected creature’s next turn starts' in outcome
    assert e._effective_speed(victim)==(0 if zero else 20 if owned else 30)
    assert bool(any(x.condition_id=='condition:typed.reaction_denied' for x in victim.conditions.values()))==(owned and zero)
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=commits(c,m)
    assert len([x for x in e.state.actors[RIGHT].modifiers.values() if x.source_definition_id==FROZEN])==int(owned)
    turn(t,m,RIGHT);turn(t,m,LEFT)
    e=commits(c,m)
    assert not any(x.source_definition_id==FROZEN for x in e.state.actors[RIGHT].modifiers.values())
    assert not any(x.source_definition_id==FROZEN for x in e.state.actors[RIGHT].conditions.values())


def test_frozen_does_not_trigger_on_success_or_unrelated_save(tmp_path):
    c,t,m=fight(tmp_path,[FROZEN],prepare=[save([damage(1,'fire')])],bundle_edit=typed_prepare('fire'))
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    assert not any(x.source_definition_id==FROZEN for x in commits(c,m).state.actors[RIGHT].modifiers.values())
    c,t,m=fight(tmp_path/'success',[FROZEN],prepare=[save([damage(1,'cold')])],bundle_edit=typed_prepare('ice'),right_score=1000)
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    assert not any(x.source_definition_id==FROZEN for x in commits(c,m).state.actors[RIGHT].modifiers.values())


@pytest.mark.parametrize('owned',[False,True])
def test_furnace_rewards_only_actual_damage_after_hurt_and_once_round(tmp_path,owned):
    c,t,m=fight(tmp_path,[FURNACE] if owned else [],prepare=[damage(12,'cold','self'),damage(3,'fire')])
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=commits(c,m)
    assert e.state.actors[LEFT].temporary_hp==(8 if owned else 0)
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    assert commits(c,m).state.actors[LEFT].temporary_hp==0  # damage spent the offer, no repeat reward


def test_furnace_overlap_reduces_only_first_fire_packet_each_round(tmp_path):
    resist={'type':'resistance','damage_types':['fire'],'applies_to':'self','duration':{'kind':'until_removed'}}
    c,t,m=fight(tmp_path,[FURNACE],prepare=[resist],cause=[damage(20,'fire')])
    resolve(lambda a:act(t,m,'Prepare',a))
    turn(t,m,RIGHT)
    resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert commits(c,m).state.actors[LEFT].current_hp==994
    resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert commits(c,m).state.actors[LEFT].current_hp==984


@pytest.mark.parametrize('alchemy',[False,True])
def test_stomach_reduction_requires_own_alchemy(tmp_path,alchemy):
    def own_alchemy(bundle):
        typed_prepare('alchemy' if alchemy else 'poison')(bundle)
        if alchemy:
            # combat/ext/alchemy_stomach.py recognizes the packet's own
            # Alchemy source, so the recorded action names a printed one.
            for a in bundle['action_catalog']:
                if a['display_name']=='Prepare':
                    a['parameters']['typed']['source']='TAL_ALCHEMY_ANTIDOTE_PILL'
    c,t,m=fight(tmp_path,[STOMACH],prepare=[damage(20,'poison','self')],bundle_edit=own_alchemy)
    resolve(lambda a:act(t,m,'Prepare',a))
    assert commits(c,m).state.actors[LEFT].current_hp==(994 if alchemy else 990)


@pytest.mark.parametrize('category',['disease','forced_transformation','mutation','bodily_corruption','ordinary'])
def test_flesh_save_advantage_uses_this_saves_categories(tmp_path,category):
    c,t,m=fight(tmp_path,[FLESH],cause=[save([damage(1,'force')],save_categories=[category])])
    turn(t,m,RIGHT)
    resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=commits(c,m);r=next(r for r in e.rolls if r.reason.startswith('SAVE:'))
    assert r.mode==('NORMAL' if category=='ordinary' else 'ADVANTAGE')


def test_flesh_healing_roll_addition_does_not_multiply_over_recipients(tmp_path):
    c,t,m=fight(tmp_path,[FLESH],prepare=[damage(30,'force','self'),{'type':'healing','flat':10,'applies_to':'self'}],bundle_edit=typed_prepare('flesh'))
    resolve(lambda a:act(t,m,'Prepare',a))
    assert commits(c,m).state.actors[LEFT].current_hp==984
    resolve(lambda a:act(t,m,'Prepare',a))
    assert commits(c,m).state.actors[LEFT].current_hp==964


@pytest.mark.parametrize('feature,category,expected_cost',[(DEMON,'emotional_manipulation',2),(HEART,'heat',0)])
def test_qualified_failed_saves_offer_real_reroll_and_pay_only_acceptance(tmp_path,feature,category,expected_cost):
    c,t,m=fight(tmp_path,[feature],left_score=1,cause=[save([damage(1,'force')],save_categories=[category])])
    turn(t,m,RIGHT)
    _,prompts=resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=commits(c,m)
    assert any(feature in str(p) for p in prompts)
    assert any(v.event_type=='D20_REWRITTEN' and v.source_definition_id==feature and v.payload['operation']=='reroll' for v in e.events)
    assert e.state.actors[LEFT].resources['resource:core.qi']==100-expected_cost
    assert e.state.actors[LEFT].reaction_available==(feature!=DEMON)


def test_heart_demon_dream_advantage_without_existing_charmed_condition(tmp_path):
    c,t,m=fight(tmp_path,[DEMON],cause=[save([damage(1,'force')],save_categories=['dream'])])
    turn(t,m,RIGHT)
    _,prompts=resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT),{'reaction:typed.'+DEMON:[]})
    e=commits(c,m)
    assert next(r for r in e.rolls if r.reason.startswith('SAVE:')).mode=='ADVANTAGE'


def test_fall_choice_lands_and_moves_only_once_scene(tmp_path, monkeypatch):
    from combat import ext, falling
    ext.effects()
    monkeypatch.setitem(ext._EFFECTS, "test_insights3_launch", lambda ctx,row: falling.displace(ctx.engine,ctx.target,4,ctx.source,intent=ctx.intent))
    launch={'type':'test_insights3_launch','applies_to':'target'}
    c,t,m=fight(tmp_path,[FALL],cause=[launch])
    turn(t,m,RIGHT)
    def pick(p):
        ids=[o['id'] for o in p.get('choice',{}).get('options',[])]
        if p['context']['reaction_source_id']=='choice:needle.rider_step':
            return ['cell:3,7'] if 'cell:3,7' in ids else ids[-1:]
        return ids[:1]
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),pick)
    e=commits(c,m)
    assert e.state.actors[LEFT].current_hp==1000
    assert e.state.actors[LEFT].position.z==0
    assert any('Fall Seven Ways' in str(p) for p in prompts)
    assert e.state.actors[LEFT].position.y==7
    _,prompts=resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert commits(c,m).state.actors[LEFT].current_hp<1000
    assert not any('Fall Seven Ways' in str(p) for p in prompts)
