"""Printed Puppetry effects through service/table commits and cold replay."""
import pytest
from combat import ext
from combat.ext import placed, vessel
from combat.typed_executor import bears_mark
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, reload, act, turn, action_sender
from tests.auto28_puppetry_support import resolve
from tests.test_auto28_puppetry import raise_at, OWNED, SPHERE

DRINKS = 'tianxia.talent.puppetry.puppet_drinks_the_blow'
RECOVERY = 'insight.severed-thread-recovery'


def insight_sheet(talents):
    def edit(doc, aid):
        if aid == LEFT:
            doc['spheres_and_talents']['cultivation_insight_record_ids'] = [i for i in talents if i.startswith('insight.')]
    return edit


def scene(tmp_path, *, talents=(), amount=100, cl=15, ally=False, cause_effects=None, **kwargs):
    c,t,m = fight(tmp_path, [*OWNED, *talents], spheres=[SPHERE], cl=cl,
        prepare=[{'type':'mark','mark':vessel.MARK,'applies_to':'target','duration':{'kind':'until_end_of_your_next_turn'}}],
        cause=cause_effects if cause_effects is not None else [{'type':'damage','flat':amount,'damage_types':['force']}], cause_target='ANY_CREATURE', sheet_edit=insight_sheet(talents),
        ally=[] if ally else None,
        positions={LEFT:{'x':3,'y':6}, RIGHT:{'x':4,'y':6}, **({ALLY:{'x':3,'y':5}} if ally else {})}, **kwargs)
    raise_at(c,t,m,4,5)
    assert act(t,m,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    return c,t,m


@pytest.mark.parametrize('amount', [100, 1])
@pytest.mark.parametrize('ai', [False, True])
def test_drinks_spends_mark_reduces_damage_and_transfers_actual_half(tmp_path, amount, ai):
    c,t,m=scene(tmp_path,talents=[DRINKS],amount=amount,ally=True)
    turn(t,m,RIGHT)
    if ai:
        c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    before=reload(c,m); zone=placed.of(before,'vessel')[0]
    hp=before.state.actors[ALLY].current_hp; vessel_hp=placed.data(zone)['hp']
    _,prompts=resolve(action_sender(c,t,m,'Cause',target_id=ALLY))
    after=reload(c,m)
    receipts=[e for e in after.events[len(before.events):] if e.source_definition_id==DRINKS and e.event_type=='PASSIVE_TRIGGERED' and 'reduction' in e.payload]
    assert len(receipts)==1
    used=receipts[0].payload['reduction']
    roll = next(r for r in after.rolls[len(before.rolls):] if r.reason == 'PUPPET_DRINKS_REDUCTION')
    # The sheet has key ability 14: +2. Assert printed dice, independently of the settlement receipt.
    assert roll.expression == '3d8+2'
    assert len(roll.dice) == 3 and all(1 <= d <= 8 for d in roll.dice)
    assert roll.modifier == 2 and roll.total == sum(roll.dice) + 2
    # Independent SHA256 oracle for the seeded committed dice; do not derive the
    # expected prevention from the extension's PASSIVE_TRIGGERED receipt.
    import hashlib
    expected_dice=tuple(int.from_bytes(hashlib.sha256(before.state.match_seed.encode() + b'\x00' +
        counter.to_bytes(16, 'big')).digest(), 'big') % 8 + 1
        for counter in range(roll.counter_start, roll.counter_start + 3))
    assert roll.dice == expected_dice
    assert used == min(amount, sum(roll.dice) + 2)
    assert after.state.actors[ALLY].current_hp==hp-(amount-used)
    assert placed.data(placed.of(after,'vessel')[0])['hp']==vessel_hp-used//2
    assert not bears_mark(after.state.actors[RIGHT],LEFT,vessel.MARK)
    assert after.state.actors[LEFT].reaction_available==before.state.actors[LEFT].reaction_available
    assert after.state.actors[LEFT].resources==before.state.actors[LEFT].resources
    assert bool([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.puppet_drinks']) is not ai


def test_ai_drinks_does_not_protect_enemy_with_allies_and_enemies_in_range(tmp_path):
    c,t,m=scene(tmp_path,talents=[DRINKS],amount=50,ally=True)
    turn(t,m,RIGHT)
    c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    before=reload(c,m)
    resolve(action_sender(c,t,m,'Cause',target_id=RIGHT))
    after=reload(c,m)
    assert after.state.actors[RIGHT].current_hp==before.state.actors[RIGHT].current_hp-50
    assert bears_mark(after.state.actors[RIGHT],LEFT,vessel.MARK)
    assert not any(e.source_definition_id==DRINKS for e in after.events[len(before.events):])


def test_drinks_decline_and_unowned_leave_damage_unchanged(tmp_path):
    c,t,m=scene(tmp_path,talents=[DRINKS],amount=40)
    turn(t,m,RIGHT);before=reload(c,m)
    resolve(action_sender(c,t,m,'Cause',target_id=LEFT),{'choice:needle.puppet_drinks':[]})
    after=reload(c,m)
    assert after.state.actors[LEFT].current_hp==before.state.actors[LEFT].current_hp-40
    assert bears_mark(after.state.actors[RIGHT],LEFT,vessel.MARK)


@pytest.mark.parametrize('cl,limit',[(14,1),(15,2)])
def test_recovery_broken_threads_counts_scene_budget_across_turns(tmp_path,monkeypatch,cl,limit):
    def damage(ctx,eff):
        for z in list(placed.of(ctx.engine,'vessel',owner_id=ctx.actor.entity_id)):
            vessel.damage_vessel(ctx.engine,z,999,ctx.source)
    ext.effects();monkeypatch.setitem(ext.effects(),'test_break_vessel',damage)
    c,t,m=fight(tmp_path,[*OWNED,RECOVERY],spheres=[SPHERE],cl=cl,
        prepare=[{'type':'test_break_vessel'}],prepare_target='SELF',sheet_edit=insight_sheet([RECOVERY]))
    for i in range(3):
        raise_at(c,t,m,4,5)
        before=reload(c,m);cp=before.state.actors[LEFT].resources['resource:core.qi']
        assert act(t,m,'Prepare')['status']=='COMMITTED'
        after=reload(c,m)
        assert after.state.actors[LEFT].resources['resource:core.qi']==cp+(i<limit)
        if i < limit:
            text=next(e.payload['text'] for e in after.events[len(before.events):] if e.source_definition_id==RECOVERY and 'text' in e.payload)
            assert 'cultivation point' in text and 'Qi' in text
        turn(t,m,RIGHT);turn(t,m,LEFT)


def test_recovery_dismissal_does_not_count_as_loss(tmp_path):
    c,t,m=scene(tmp_path,talents=[RECOVERY])
    before=reload(c,m)
    assert act(t,m,'Dismiss Vessel')['status']=='COMMITTED'
    after=reload(c,m)
    assert after.state.actors[LEFT].resources==before.state.actors[LEFT].resources
    assert not any(e.source_definition_id==RECOVERY for e in after.events[len(before.events):])


def test_drinks_reports_zero_actual_use_when_another_defense_prevents_all(tmp_path,monkeypatch):
    ext.effects()
    def prevent(engine,target,amount,*args):
        return {'amount':0}
    monkeypatch.setitem(ext._HOOKS,'final_damage',[prevent,*ext._HOOKS['final_damage']])
    c,t,m=scene(tmp_path,talents=[DRINKS],amount=100,ally=True)
    turn(t,m,RIGHT);before=reload(c,m)
    resolve(action_sender(c,t,m,'Cause',target_id=ALLY))
    after=reload(c,m)
    receipt=next(e for e in after.events[len(before.events):]
        if e.source_definition_id==DRINKS and 'reduction' in e.payload)
    assert receipt.payload['reduction']==0
    assert after.state.actors[ALLY].current_hp==before.state.actors[ALLY].current_hp
    assert placed.data(placed.of(after,'vessel')[0])['hp']==placed.data(placed.of(before,'vessel')[0])['hp']


def test_recovery_out_of_range_once_and_no_repeated_inactive_credit(tmp_path,monkeypatch):
    from combat.gate2_runtime_models import Position
    def relocate(ctx,eff):
        z=placed.of(ctx.engine,'vessel',owner_id=ctx.actor.entity_id)[0]
        placed.reshape(ctx.engine,z,center=Position(x=20,y=5),cells=[Position(x=20,y=5)])
    ext.effects();monkeypatch.setitem(ext.effects(),'test_far_vessel',relocate)
    c,t,m=fight(tmp_path,[*OWNED,RECOVERY],spheres=[SPHERE],
        sheet_edit=insight_sheet([RECOVERY]),prepare=[{'type':'test_far_vessel'}],prepare_target='SELF')
    raise_at(c,t,m,4,5)
    assert act(t,m,'Prepare')['status']=='COMMITTED'
    before=reload(c,m)
    assert act(t,m,'end')['status']=='COMMITTED'
    after=reload(c,m)
    assert after.state.actors[LEFT].resources['resource:core.qi']==before.state.actors[LEFT].resources['resource:core.qi']+1
    turn(t,m,LEFT)
    assert act(t,m,'end')['status']=='COMMITTED'
    assert reload(c,m).state.actors[LEFT].resources==after.state.actors[LEFT].resources


def test_unowned_drinks_does_not_run(tmp_path):
    c,t,m=scene(tmp_path,amount=40)
    turn(t,m,RIGHT);before=reload(c,m)
    resolve(action_sender(c,t,m,'Cause',target_id=LEFT))
    after=reload(c,m)
    assert after.state.actors[LEFT].current_hp==before.state.actors[LEFT].current_hp-40
    assert bears_mark(after.state.actors[RIGHT],LEFT,vessel.MARK)


@pytest.mark.parametrize('ai_owner', [False, True])
@pytest.mark.parametrize('hidden_id', [ALLY, RIGHT])
def test_manual_printed_eligibility_and_ai_perception(tmp_path, monkeypatch, ai_owner, hidden_id):
    from combat.target_knowledge import located
    from combat.typed_executor import run_effects
    from dataclasses import replace
    # Deliver an untargeted packet: invisible creatures are not offered as
    # direct action targets. Keep the real action/actor and normal damage path.
    def packet(ctx, effect):
        ally=ctx.engine.state.actors[ALLY]
        run_effects(replace(ctx,target=ally,targets=[ally]),
                    [{'type':'damage','flat':40,'damage_types':['force']}])
    ext.effects();monkeypatch.setitem(ext.effects(),'test_unseen_packet',packet)
    c,t,m=scene(tmp_path,talents=[DRINKS],amount=40,ally=True,
        cause_effects=[{'type':'test_unseen_packet'}],extra_actions=[('Conceal', {'target_kind':'ANY_CREATURE', 'effects':[
            {'type':'condition','condition':'invisible','applies_to':'target','duration':{'kind':'until_removed'}}]})])
    assert act(t,m,'Conceal',target_id=hidden_id)['status']=='COMMITTED'
    turn(t,m,RIGHT)
    if ai_owner:
        c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    before=reload(c,m)
    assert not located(before,before.state.actors[LEFT],before.state.actors[hidden_id])
    _,prompts=resolve(action_sender(c,t,m,'Cause',target_id=RIGHT))
    after=reload(c,m)
    receipts=[e for e in after.events[len(before.events):] if e.source_definition_id==DRINKS and 'reduction' in e.payload]
    assert bool(receipts) is not ai_owner
    assert bool(prompts) is not ai_owner
    assert bears_mark(after.state.actors[RIGHT],LEFT,vessel.MARK) is ai_owner
    if ai_owner:
        assert after.state.actors[ALLY].current_hp==before.state.actors[ALLY].current_hp-40
    else:
        assert after.state.actors[ALLY].current_hp>before.state.actors[ALLY].current_hp-40


@pytest.mark.parametrize('ai_action', [False, True])
@pytest.mark.parametrize('amount', [100, 1])
def test_second_vessel_choice_and_trigger_context(tmp_path, ai_action, amount):
    def names(bundle):
        actor=bundle['actor_template']
        actor['display_name']={LEFT:'Puppeteer', RIGHT:'Striker', ALLY:'Protected ally'}[actor['entity_id']]
    c,t,m=scene(tmp_path,talents=[DRINKS,vessel.TWO_BODY],amount=amount,ally=True,bundle_edit=names)
    turn(t,m,RIGHT);turn(t,m,LEFT)
    raise_at(c,t,m,2,5)
    # Refresh the mark after advancing through the turn boundary.
    assert act(t,m,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    turn(t,m,RIGHT)
    before=reload(c,m)
    zones=placed.of(before,'vessel')
    assert len(zones)==2
    selected=zones[1].zone_id
    _,prompts=resolve(action_sender(c,t,m,'Cause',target_id=ALLY,ai=ai_action),
                     {'choice:needle.puppet_drinks_vessel':[selected]})
    after=reload(c,m)
    assert len(prompts)==2
    for prompt in prompts:
        assert prompt['context']['reactor_id']==LEFT
        assert prompt['action']=='Cause'
        assert prompt['trigger_actor']=='Striker' and prompt['affected']=='Protected ally'
        assert prompt['trigger_actor'] in prompt['moment'] and prompt['affected'] in prompt['moment']
    assert 'attached thread' in prompts[0]['moment']
    assert '3d8 + 2' in prompts[0]['moment']
    assert 'cultivation points' in prompts[0]['moment']
    assert prompts[1]['choice']['allow_decline'] is False
    roll=next(r for r in after.rolls[len(before.rolls):] if r.reason=='PUPPET_DRINKS_REDUCTION')
    assert roll.expression=='3d8+2' and roll.modifier==2 and len(roll.dice)==3
    used=min(amount,sum(roll.dice)+2)
    assert after.state.actors[ALLY].current_hp==before.state.actors[ALLY].current_hp-(amount-used)
    after_zones={z.zone_id:z for z in placed.of(after,'vessel')}
    for zone in zones:
        assert placed.data(after_zones[zone.zone_id])['hp']==placed.data(zone)['hp']-(used//2 if zone.zone_id==selected else 0)
    assert not bears_mark(after.state.actors[RIGHT],LEFT,vessel.MARK)
