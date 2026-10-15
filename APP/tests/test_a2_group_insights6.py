"""Printed Insight clauses through CombatService, journaled table intents and cold reload.

Only incoming effects/activation costs are synthetic; Insight ownership comes
from the real cultivation_insight_record_ids field and reviewed source hashes.
"""
from pathlib import Path
import json
import pytest
from combat.ext import effect
from combat.ext import insights6 as ix

POISE = 'insight.poise-tempered-presence'
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, fight as service_fight, reload, resolve, turn, action_sender
from combat import posture


def fight(tmp_path, insights=(), **kwargs):
    extra_sheet_edit = kwargs.pop('sheet_edit', None)
    def fields(doc, aid):
        f = doc['spheres_and_talents']
        ids = f.get('learned_talent_record_ids', [])
        f['cultivation_insight_record_ids'] = [k for k in (insights if aid == LEFT else kwargs.get('right_talents', ())) if k.startswith('insight.')]
        f['learned_talent_record_ids'] = [k for k in ids if not k.startswith('insight.')]
        if extra_sheet_edit is not None:
            extra_sheet_edit(doc, aid)
    return service_fight(tmp_path, insights, sheet_edit=fields, **kwargs)


def packets(engine):
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED']


@effect('test_insights6_refund')
def refund(ctx, row):
    ctx.engine._gain_resource(ctx.actor, ix.QI, row['amount'], ctx.source, cost_source_id=ctx.source)


@effect('test_insights6_independent_payment')
def independent_payment(ctx, row):
    from combat.paid_relocation import activation
    with activation(ctx.engine, ctx.actor, 'test:independent-payment'):
        ctx.engine._spend_resource(ctx.actor, ix.QI, row['amount'], 'test:independent-payment')


@pytest.mark.parametrize('paid,refund_amount,expected', [(0,0,100),(1,0,99),(2,0,99),(3,0,98),(3,2,99),(4,2,99)])
def test_economy_uses_actual_net_paid_qi_after_completion(tmp_path, paid, refund_amount, expected):
    rows = [{'type': 'temp_hp', 'applies_to': 'self', 'flat': 1}]
    if refund_amount:
        rows.append({'type': 'test_insights6_refund', 'amount': refund_amount})
    combat, table, mid = fight(tmp_path, [ix.ECONOMY], prepare=rows, prepare_target='SELF',
                              prepare_costs=[(ix.QI, paid)] if paid else [])
    resolve(lambda a: act(table, mid, 'Prepare', a))
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[ix.QI] == expected
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.source_definition_id == ix.ECONOMY]
    assert len(gains) == int(paid-refund_amount >= 2)


def test_economy_once_per_turn_and_independent_payment_is_not_parent_cost(tmp_path):
    combat, table, mid = fight(tmp_path, [ix.ECONOMY], prepare=[{'type':'test_insights6_independent_payment','amount':2}],
                              prepare_target='SELF')
    resolve(lambda a: act(table, mid, 'Prepare', a))
    assert reload(combat, mid).state.actors[LEFT].resources[ix.QI] == 98
    assert not any(e.source_definition_id == ix.ECONOMY for e in reload(combat, mid).events)
    # Each parent pays two, but recovery is once per actual owner turn.
    combat2, table2, mid2 = fight(tmp_path / 'paid', [ix.ECONOMY], prepare=[{'type':'temp_hp','flat':1,'applies_to':'self'}],
                               prepare_target='SELF', prepare_costs=[(ix.QI,2)])
    for _ in range(2):
        resolve(lambda a: act(table2, mid2, 'Prepare', a))
    assert reload(combat2, mid2).state.actors[LEFT].resources[ix.QI] == 97
    turn(table2, mid2, RIGHT); turn(table2, mid2, LEFT)
    resolve(lambda a: act(table2, mid2, 'Prepare', a))
    assert reload(combat2, mid2).state.actors[LEFT].resources[ix.QI] == 96


@pytest.mark.parametrize('owned', [False,True])
@pytest.mark.parametrize('category', ['smoke','inhaled_hazard','altitude','suffocation','environmental_pressure','unrelated'])
def test_breath_save_advantage_needs_own_insight_and_exact_provenance(tmp_path, owned, category):
    rows=[{'type':'save','ability':'con','save_categories':[category],
           'on_fail':[{'type':'damage','flat':1,'damage_types':['force']}],'on_success':[]}]
    combat, table, mid = fight(tmp_path, [ix.BREATH] if owned else [], cause=rows)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    engine = reload(combat, mid)
    saves=[r for r in engine.rolls if str(r.reason).startswith('SAVE:')]
    assert saves[-1].mode == ('ADVANTAGE' if owned and category != 'unrelated' else 'NORMAL')


@pytest.mark.parametrize('choice', ['dash','disengage'])
def test_breath_recovery_after_successful_stomping_step_once_scene(tmp_path, choice):
    step='tianxia.path.body_refining.feature.stomping_step'
    combat, table, mid = fight(tmp_path, [ix.BREATH,step], prepare=[{'type':'temp_hp','flat':1,'applies_to':'self'}], prepare_costs=[(ix.STAMINA,2)],
                              prepare_target='SELF', left_resource='Stamina')
    resolve(lambda a: act(table, mid, 'Prepare', a))
    resolve(lambda a: act(table, mid, 'Stomping Step', a), {'choice:needle.dash_or_disengage':[choice]})
    assert reload(combat, mid).state.actors[LEFT].resources[ix.STAMINA] == 99
    turn(table, mid, RIGHT);turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, 'Stomping Step', a), {'choice:needle.dash_or_disengage':[choice]})
    assert reload(combat, mid).state.actors[LEFT].resources[ix.STAMINA] == 99


@pytest.mark.parametrize('owned,immune', [(False,False),(True,False),(True,True)])
def test_pincer_requires_real_applied_joint_lock_and_expires(tmp_path, owned, immune):
    lock='tianxia.subpath.body.mantis_style.feature.joint_lock'
    def immunity(bundle):
        if immune and bundle['actor_id'] == RIGHT:
            bundle['typed_passives'].append({'block':'condition_immunity','conditions':['restrained']})
    combat, table, mid = fight(tmp_path, ([ix.PINCER] if owned else [])+[lock], left_resource='Stamina',
        prepare=[{'type':'condition','condition':'grappled','applies_to':'target','duration':{'kind':'until_removed'}}], bundle_edit=immunity)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    resolve(lambda a: act(table, mid, 'Joint Lock', a, target_id=RIGHT))
    engine = reload(combat, mid)
    held = [c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == ix.PINCER_HOLD]
    assert bool(held) == (owned and not immune)
    if held:
        assert engine._effective_speed(engine.state.actors[RIGHT]) == 0
        assert held[0].source_actor_id == LEFT
    turn(table, mid, RIGHT); turn(table, mid, LEFT)
    assert not any(c.condition_id == ix.PINCER_HOLD for c in reload(combat, mid).state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('distance,owned', [(0,True),(5,True),(10,True),(0,False)])
def test_one_breath_adds_con_to_original_hit_roll_and_ac_once(tmp_path, distance, owned):
    rows=[]
    if distance:
        rows.append({'type':'rider_step','distance_ft':distance,'no_oa':True})
    rows.append({'type':'attack','attack_kind':'unarmed','dice':{'count':1,'sides':4},'damage_types':['bludgeoning']})
    combat, table, mid = fight(tmp_path, [ix.ONE] if owned else [], prepare=rows, prepare_attack_bonus=100,
                              positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6}})
    picks={'choice:needle.rider_step': [f'cell:3,{6-distance//5}']} if distance else {}
    # Keep the target in synthetic technique range after the chosen free step.
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT), picks)
    engine=reload(combat,mid)
    rolls=[r for r in engine.rolls if str(r.reason).startswith('DAMAGE:')]
    assert rolls[-1].modifier == (2 if owned and distance<=5 else 0)
    ac=[m for m in engine.state.actors[LEFT].modifiers.values() if m.target_field=='armor_class']
    assert len(ac)==int(owned and distance<=5)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT), {'choice:needle.rider_step':[]})
    engine=reload(combat,mid)
    assert [r for r in engine.rolls if str(r.reason).startswith('DAMAGE:')][-1].modifier == 0



@pytest.mark.parametrize('standing_insight,cost,bonus', [
    (None, 15, 0),
    ('insight.fall-seven-ways', 5, 2),
])
def test_one_breath_counts_actual_standing_cost_across_reload(tmp_path, standing_insight, cost, bonus):
    def strike_bonus(bundle):
        for action in bundle['action_catalog']:
            if action.get('display_name') == 'Unarmed Test Strike':
                action['parameters']['typed']['numbers']['attack_bonus'] = 100
    owned = [ix.ONE] + ([standing_insight] if standing_insight else [])
    combat, table, mid = fight(tmp_path, owned, prepare=[
        {'type': 'condition', 'condition': 'prone', 'applies_to': 'self'}], prepare_target='SELF',
        extra_actions=[('Unarmed Test Strike', {'target_kind': 'HOSTILE_ENTITY', 'effects': [
            {'type': 'attack', 'attack_kind': 'unarmed', 'dice': {'count': 1, 'sides': 4},
             'damage_types': ['bludgeoning']} ]})],
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}}, bundle_edit=strike_bonus)
    resolve(lambda a: act(table, mid, 'Prepare', a))
    before_stand = reload(combat, mid).state.actors[LEFT].position
    assert any(c.expires_on == 'STAND_UP' for c in reload(combat, mid).state.actors[LEFT].conditions.values())
    resolve(action_sender(combat, table, mid, posture.SOURCE))
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].position == before_stand
    stood = [e for e in engine.events if e.event_type == 'STOOD_UP' and e.actor_id == LEFT]
    assert stood and stood[-1].payload['cost_ft'] == cost
    assert not any(c.expires_on == 'STAND_UP' for c in engine.state.actors[LEFT].conditions.values())
    resolve(lambda a: act(table, mid, 'Unarmed Test Strike', a, target_id=RIGHT))
    engine = reload(combat, mid)
    damage_roll = [r for r in engine.rolls if str(r.reason).startswith('DAMAGE:')][-1]
    assert damage_roll.modifier == bonus
    assert bool([m for m in engine.state.actors[LEFT].modifiers.values() if m.target_field == 'armor_class']) == (bonus == 2)

@pytest.mark.parametrize('feature,range_ft,cost', [('TAL_VOID_RETURN_TO_ZERO',75,4),('TAL_VOID_CAUSE_EMPTYING_REVERSAL',105,8)])
@pytest.mark.parametrize('owned',[False,True])
def test_null_script_reaches_real_reaction_beyond_normal_range(tmp_path,feature,range_ft,cost,owned):
    combat,table,mid=fight(tmp_path,[feature]+([ix.NULL] if owned else []), spheres=['tianxia.sphere.void'],
        cause=[{'type':'ac_bonus','applies_to':'self','flat':2,'duration':{'kind':'one_minute'}}],cause_target='SELF',
        arena_edit=lambda a: a.update(width_squares=30),
        positions={LEFT:{'x':1,'y':6},RIGHT:{'x':1+range_ft//5,'y':6}})
    turn(table,mid,RIGHT)
    resolve(lambda a: act(table,mid,'Cause',a))
    engine=reload(combat,mid)
    assert engine.state.actors[LEFT].resources[ix.QI]==100-(cost if owned else 0)
    if feature=='TAL_VOID_RETURN_TO_ZERO':
        assert bool([m for m in engine.state.actors[RIGHT].modifiers.values() if m.target_field=='armor_class' and m.value==2]) == (not owned)


@pytest.mark.parametrize('category,failed', [('nightmare',True),('unrelated',True),('nightmare',False)])
def test_nightmare_reward_once_round_after_final_enemy_save(tmp_path,category,failed):
    rows=[{'type':'save','ability':'wis','save_categories':[category],
           'on_fail':[{'type':'damage','flat':1,'damage_types':['psychic']}],'on_success':[]}]
    combat,table,mid=fight(tmp_path,[ix.NIGHTMARE],prepare=rows,left_save_dc=100 if failed else 1)
    for _ in range(2):resolve(lambda a: act(table,mid,'Prepare',a,target_id=RIGHT))
    engine=reload(combat,mid)
    assert engine.state.actors[LEFT].temporary_hp==(4 if category=='nightmare' and failed else 0)
    assert len([e for e in engine.events if e.source_definition_id==ix.NIGHTMARE])==int(category=='nightmare' and failed)


def test_nightmare_reward_on_failed_native_repeat_save_and_cold_reload(tmp_path):
    rows=[{'type':'condition','condition':'frightened','applies_to':'target',
           'repeat_save':{'when':'end','ability':'wis'}}]
    combat,table,mid=fight(tmp_path,[ix.NIGHTMARE],prepare=rows)
    resolve(lambda a:act(table,mid,'Prepare',a,target_id=RIGHT))
    turn(table,mid,RIGHT)
    resolve(lambda a:act(table,mid,'end',a))
    engine=reload(combat,mid)
    assert engine.state.actors[LEFT].temporary_hp==4
    assert any(e.source_definition_id==ix.NIGHTMARE for e in engine.events)


def _sleep_fight(tmp_path, insights):
    """Left owns Nightmare Feaster and the real Sleep talent; an ally does the seeding.

    Only ownership and who casts which talent differ. Sleep's Wisdom save, its
    dream_sleep condition and the end-of-turn repeat are the reviewed Dreams rows
    the compiler already built, so nothing about the effect is written here.
    """
    def ally_talents(doc, aid):
        if aid == ALLY:
            doc['spheres_and_talents']['sphere_record_ids'] = ['tianxia.sphere.dreams']
            doc['spheres_and_talents']['learned_talent_record_ids'] = ['TAL_DREAM_SLEEP']
    return fight(tmp_path, list(insights) + ['TAL_DREAM_SLEEP'], spheres=['tianxia.sphere.dreams'],
                 ally=[], sheet_edit=ally_talents)


def _wait_for(table, mid, actor_id, limit=8):
    """End turns until this creature is the one deciding."""
    for _ in range(limit):
        if table.state(mid)['menu'].get('actor_id') == actor_id:
            return
        resolve(lambda a: act(table, mid, 'end', a))
    raise AssertionError(f'{actor_id} never became the active actor')


def _nightmare_grants(engine):
    return [e for e in engine.events if e.source_definition_id == ix.NIGHTMARE
            and e.event_type == 'TEMP_HP_GRANTED']


@pytest.mark.parametrize('owned', [True, False])
def test_nightmare_reward_on_failed_repeat_save_of_real_sleep_in_a_later_round(tmp_path, owned):
    """A failed native repeat save counts as a Dreams save, exactly as the initial one did.

    The reward is once per round, and temporary hit points do not stack, so this
    watches the printed grants: Sleep's own failed save spends the round it was
    cast in, and the sleeper's failed repeat save in a later round earns the next
    one. Without the Insight the sleeper simply keeps failing its saves.
    """
    combat, table, mid = _sleep_fight(tmp_path, [ix.NIGHTMARE] if owned else [])
    # Round 1: the ally plants the real Dream Seed, so the target is Drowsy when Sleep is offered.
    _wait_for(table, mid, ALLY)
    resolve(lambda a: act(table, mid, 'Dream Seed', a, target_id=RIGHT))
    # Round 2: Sleep's own Wisdom save fails and puts the real dream_sleep condition on the target.
    _wait_for(table, mid, LEFT)
    resolve(lambda a: act(table, mid, 'Sleep', a, target_id=RIGHT))
    engine = reload(combat, mid)
    dream_sleep = [c for c in engine.state.actors[RIGHT].conditions.values()
                   if c.condition_id == 'condition:typed.dream_sleep']
    assert dream_sleep and (dream_sleep[0].data.get('repeat_save') or {}).get('when') == 'end'
    assert dream_sleep[0].source_definition_id.endswith('TAL_DREAM_SLEEP')
    assert len(_nightmare_grants(engine)) == int(owned)  # the initial save spent this round's reward

    # Later rounds: the sleeper keeps failing the repeat save Sleep printed on it.
    for _ in range(6):
        if engine.state.round_number >= 3 and len(_nightmare_grants(engine)) >= int(owned) * 2:
            break
        resolve(lambda a: act(table, mid, 'end', a))
        engine = reload(combat, mid)
    assert engine.state.round_number >= 3, 'the sleeper never reached a later round'
    assert len(_nightmare_grants(engine)) == (2 if owned else 0)


def test_poise_uses_final_overridden_native_repeat_save_and_player_consent(tmp_path,monkeypatch):
    from combat import ext
    rows=[{'type':'save','ability':'wis','on_fail':[{'type':'condition','condition':'frightened',
           'repeat_save':{'when':'end','ability':'wis'}}],'on_success':[]}]
    combat,table,mid=fight(tmp_path,[],right_talents=[POISE],prepare=rows,left_save_dc=100)
    settled=[]
    monkeypatch.setitem(ext._HOOKS,'repeat_save_failed',list(ext._HOOKS.get('repeat_save_failed',[]))+[
        lambda engine,resolution:{'result':'SUCCESS','settled_by':'test:repeat-save-final'}])
    monkeypatch.setitem(ext._HOOKS,'repeat_save_final',list(ext._HOOKS.get('repeat_save_final',[]))+
        [lambda engine,resolution:settled.append(dict(resolution))])
    resolve(lambda a:act(table,mid,'Prepare',a,target_id=RIGHT))
    turn(table,mid,RIGHT)
    _,prompts=resolve(lambda a:act(table,mid,'end',a),{'choice:needle.' + POISE:['use']})
    engine=reload(combat,mid)
    marks=[c for c in engine.state.actors[LEFT].conditions.values() if 'beauty_mark' in c.condition_id]
    assert marks and marks[0].source_actor_id==RIGHT, f'resolutions={settled!r}; prompts={prompts!r}'
    assert any('Beauty Mark' in str(p) for p in prompts)


def test_nightmare_reward_applies_to_allied_failed_save(tmp_path):
    def area(bundle):
        for action in bundle['action_catalog']:
            if action.get('display_name')=='Prepare':
                action['parameters']['typed']['area']={'shape':'sphere','size_ft':20,'centered_on_self':True}
    combat,table,mid=fight(tmp_path,[ix.NIGHTMARE],left_save_dc=100,ally=[],prepare_target='SELF',bundle_edit=area,
        prepare=[{'type':'save','ability':'wis','applies_to':'creatures_in_area','save_categories':['nightmare'],
                  'on_fail':[],'on_success':[]}],
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':8,'y':6},'actor:factory.h15-ally':{'x':3,'y':5}},
        arena_edit=lambda arena:arena.update(width_squares=20))
    resolve(lambda a:act(table,mid,'Prepare',a))
    engine=reload(combat,mid)
    assert engine.state.actors[LEFT].temporary_hp==4
    assert len([e for e in engine.events if e.source_definition_id==ix.NIGHTMARE])==1


@pytest.mark.parametrize('decline', [False,True])
def test_poise_optional_source_mark_once_scene_and_source_owned_expiry(tmp_path,decline):
    rows=[{'type':'save','ability':'wis','on_fail':[{'type':'condition','condition':'frightened'}],'on_success':[]}]
    combat,table,mid=fight(tmp_path,[POISE],cause=rows,cause_save_dc=1)
    turn(table,mid,RIGHT)
    picks={'choice:needle.' + POISE:[]} if decline else {}
    resolve(lambda a: act(table,mid,'Cause',a,target_id=LEFT),picks)
    engine=reload(combat,mid)
    marks=[c for c in engine.state.actors[RIGHT].conditions.values() if 'beauty_mark' in c.condition_id]
    assert bool(marks)==(not decline)
    if marks: assert marks[0].source_actor_id==LEFT
    turn(table,mid,LEFT)
    resolve(lambda a: act(table,mid,'end',a))
    assert not any('beauty_mark' in c.condition_id for c in reload(combat,mid).state.actors[RIGHT].conditions.values())


def test_reviewed_complete_clauses_have_no_combat_reminder_rows():
    m=json.loads((Path(__file__).parents[1]/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    for k in [ix.ECONOMY,ix.PINCER,ix.ONE]:
        assert m[k]['coverage']=='FULL' and m[k]['riders']==[]
    assert m[POISE]['coverage']=='CORE_WITH_RIDERS'
    assert m[POISE]['riders']==[
        'Charmed and Frightened saves resolve automatically. For humiliating or compelled actions described only in the story, the table still decides whether this Insight applies.'
    ]


@pytest.mark.parametrize('paid,expected',[ (2,99), (3,99), (4,98)])
def test_economy_after_golden_core_efficiency_actual_refund(tmp_path,paid,expected):
    efficiency='tianxia.path.qi_cultivation.feature.golden_core_efficiency'
    combat,table,mid=fight(tmp_path,[ix.ECONOMY,efficiency],
        prepare=[{'type':'temp_hp','flat':1,'applies_to':'self'}],prepare_target='SELF',prepare_costs=[(ix.QI,paid)])
    resolve(lambda a: act(table,mid,'Prepare',a))
    engine=reload(combat,mid)
    assert engine.state.actors[LEFT].resources[ix.QI]==expected
    gains=[e for e in engine.events if e.event_type=='RESOURCE_GAINED']
    refunds=[e for e in gains if e.payload.get('cost_source_id')]
    assert len(refunds)==1 and refunds[0].payload['gained']==1
    assert len([e for e in gains if e.source_definition_id==ix.ECONOMY])==int(paid>=3)


@pytest.mark.parametrize('distance,source_cl,expected',[(5,20,0),(15,20,5),(15,5,0)])
def test_mountain_route_reduction_source_cl_and_reload(tmp_path,distance,source_cl,expected):
    def source(bundle):
        for action in bundle['action_catalog']:
            if action['display_name']=='Cause':action['parameters']['typed']['numbers']['cl']=source_cl
    combat,table,mid=fight(tmp_path,[ix.MOUNTAIN],cause=[{'type':'forced_movement','distance_ft':distance,'direction':'away'}],
        bundle_edit=source,positions={LEFT:{'x':6,'y':6},RIGHT:{'x':5,'y':6}})
    turn(table,mid,RIGHT)
    before=reload(combat,mid).state.actors[LEFT].position
    resolve(lambda a:act(table,mid,'Cause',a,target_id=LEFT))
    engine=reload(combat,mid)
    assert engine.grid.distance_ft(before,engine.state.actors[LEFT].position)==expected
    resolve(lambda a:act(table,mid,'Cause',a,target_id=LEFT))
    engine=reload(combat,mid)
    assert engine.grid.distance_ft(before,engine.state.actors[LEFT].position)==expected+max(0,distance-10)


@pytest.mark.parametrize('auto',[False,True])
def test_nightmare_area_recipients_are_enemies_and_reward_once(tmp_path,auto):
    from tests.auto_worker1_support import ALLY
    from tests.hunt15_support import action_sender
    def area(bundle):
        for action in bundle['action_catalog']:
            if action['display_name']=='Prepare':
                action['parameters']['typed']['area']={'shape':'sphere','size_ft':20,'centered_on_self':True}
    rows=[{'type':'save','ability':'wis','applies_to':'enemies_in_area','save_categories':['nightmare'],
           'on_fail':[{'type':'damage','flat':3,'damage_types':['psychic']}],'on_success':[]}]
    combat,table,mid=fight(tmp_path,[ix.NIGHTMARE],prepare=rows,prepare_target='SELF',ally=[],bundle_edit=area,
                          extra_witness=True, positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':2,'y':6}})
    resolve(action_sender(combat,table,mid,'Prepare',ai=auto))
    engine=reload(combat,mid)
    assert engine.state.actors[LEFT].current_hp==1000 and engine.state.actors[ALLY].current_hp==1000
    assert engine.state.actors[RIGHT].current_hp==997
    assert engine.state.actors['actor:factory.auto111-witness'].current_hp==997
    assert engine.state.actors[LEFT].temporary_hp==4
    assert len([e for e in engine.events if e.source_definition_id==ix.NIGHTMARE])==1


def test_mountain_core_player_summary_spells_out_cultivation_level(tmp_path):
    # Review r10 finding 1: the compiled sheet sentence must not leave "Source-CL" undefined.
    from tests.test_auto_insights import _sheet, OWNER, _boundary
    from combat.factory_compiler import compile_character
    from combat.gate3_storage import load_typed_bundles
    bundle = compile_character(_sheet([ix.MOUNTAIN]), actor_id=OWNER)
    summary = ' '.join(_boundary(bundle, ix.MOUNTAIN)['table_applies'])
    assert 'Source-CL' not in summary
    assert 'Source CL' not in summary
    assert 'a rule with a lower Cultivation Level than yours' in summary
    # The same sentence is what a player reads in a live table: it compiles with the
    # character, the table executes an intent that uses the feature, and the sentence
    # survives a cold reload of the fight from disk.
    def source(bundle):
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Cause':
                action['parameters']['typed']['numbers']['cl'] = 5
    combat, table, mid = fight(tmp_path, [ix.MOUNTAIN],
        cause=[{'type': 'forced_movement', 'distance_ft': 15, 'direction': 'away'}],
        bundle_edit=source, positions={LEFT: {'x': 6, 'y': 6}, RIGHT: {'x': 5, 'y': 6}})
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[LEFT].position
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    engine = reload(combat, mid)
    # Source CL 5 is lower than the owner's Cultivation Level 15, so the once-per-round
    # stop zeroes this forced movement (the general ten-foot trait alone would leave 5).
    assert engine.grid.distance_ft(before, engine.state.actors[LEFT].position) == 0
    stored = next(b for b in load_typed_bundles(combat._match_dir(mid)) if b['actor_id'] == LEFT)
    stored_summary = ' '.join(_boundary(stored, ix.MOUNTAIN)['table_applies'])
    assert 'Source-CL' not in stored_summary
    assert 'Source CL' not in stored_summary
    assert 'a rule with a lower Cultivation Level than yours' in stored_summary
