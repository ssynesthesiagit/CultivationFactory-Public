"""Review blockers exercised by sealed service intents and cold mechanical replay."""
import json
import pytest
from combat.ext import effect
from combat.ext.death_riders import SOVEREIGN
from combat.ext.death_servants import LAST_ASSAULT
from combat.ext.fate_riders import WHEEL
from combat.tabletop_service import TabletopService
from tests.worker2_support import OWNER, ALLY, FOE, fixture, turn, candidate, settle, reload, sealed_native_attack
from tests.test_a2_death_second_pass import preparation, direct, servant
from tests.test_a2_death_commander import commander_bundle
from tests.test_a2_death_boundaries import reseal, supplied_successor


@effect('test_death_fix_input', harmful=False)
def scenario_input(ctx, row):
    # Represent existing effects as evented inputs; their real registered folds
    # supply the damage. No engine/roller replacement or mocked bonus provider.
    if row.get('damage_bonuses'):
        ctx.engine._apply_condition(ctx.actor, WHEEL, 'TAL_FATE_TURNING_WHEEL_AUSPICE', OWNER,
            expires_on='UNTIL_REMOVED', data={'kind':'attack', 'bonus':3})
        ctx.actor.turn_flags['hunger_marrow_damage'] = 4
    if row.get('sovereign'):
        ctx.engine._apply_condition(ctx.actor, SOVEREIGN, 'TAL_DEATH_DEATH_SOVEREIGN_INCARNATION', OWNER,
            expires_on='UNTIL_REMOVED')
    if row.get('incapacitate'):
        formation = servant(ctx.engine, 'grave_formation')
        ctx.engine._apply_condition(formation, 'condition:typed.' + row['incapacitate'], ctx.source, OWNER,
            expires_on='UNTIL_REMOVED')


def input_action(bundles, row):
    b = bundles[0]
    sid = 'action:test.death_fix_input'
    b['action_catalog'].append({'source_definition_id':sid,'display_name':'Set review scenario',
        'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF',
        'parameters':{'typed':{'source':sid,'effects':[{'type':'test_death_fix_input',**row}],
                              'numbers':{},'riders':[],'duration':{'kind':'instant'}}}})
    b['actor_template']['action_ids'].append(sid)


class RecordingTable(TabletopService):
    """Retain the unmodified public presentation input and output for assertions."""
    def _reaction_prompt(self, match_id, context, **kwargs):
        self.contexts.append(context)
        return super()._reaction_prompt(match_id, context, **kwargs)


def recording_table(combat, tmp_path):
    table = RecordingTable(combat, tmp_path)
    table.contexts = []
    return table


@pytest.mark.parametrize('maximum', [False, True])
@pytest.mark.parametrize('sovereign', [False, True])
def test_object_resolves_sealed_damage_folds_and_critical_reload(tmp_path, maximum, sovereign):
    def transform(bundles):
        preparation({'object_material':'wood' if maximum else 'stone'})(bundles)
        input_action(bundles, {'damage_bonuses':True,'sovereign':sovereign})
        for a in bundles[0]['action_catalog']:
            data = a.get('parameters',{}).get('typed',{})
            if data.get('source') == 'TAL_DEATH_ROTTING_GRASP':
                data['numbers']['attack_bonus'] = 100
        reseal(bundles)
    combat, table, mid = fixture(tmp_path, ['TAL_DEATH_ROTTING_GRASP'], cl=5,
        seed='DEATH-R1-CRIT-23', bundle_transform=transform)
    direct(combat, mid, 'Set servant scenario')
    direct(combat, mid, 'Set review scenario')
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].turn_flags['hunger_marrow_damage'] == 4
    settle(table, mid, candidate(combat, mid, 'Rotting Grasp', target='object:death-second-decay').candidate_id,
        choices={'choice:needle.rotting_object_damage':['maximum']})
    engine = reload(tmp_path, mid)
    attack = next(r for r in reversed(engine.rolls) if r.reason.startswith('ATTACK:') and r.actor_id==OWNER)
    assert attack.natural_result == 20  # deterministic actual critical, never conditional
    count, sides = (6,10) if sovereign else (2,8)
    amount = 500 - engine.state.objects['object:death-second-decay'].current_hp
    if maximum:
        assert amount == 2*count*sides + 7
    else:
        rolled = next(r for r in reversed(engine.rolls) if r.reason.startswith('DAMAGE:') and r.actor_id==OWNER)
        assert rolled.expression == f'{2*count}d{sides}+7'
        assert amount == rolled.total
    assert engine.state.actors[OWNER].turn_flags['hunger_marrow_damage'] == 0
    assert any(c.condition_id==WHEEL for c in engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('condition', ['stunned','paralyzed','incapacitated'])
def test_ineligible_commander_preserves_allowance_for_successor(tmp_path, condition):
    def transform(bundles):
        input_action(bundles, {'incapacitate':condition})
        input_row = {'type':'test_death_scene_successor'}
        b=bundles[0]; sid='action:test.death_fix_successor'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Supply review successor',
            'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF',
            'parameters':{'typed':{'source':sid,'effects':[input_row],'numbers':{},'riders':[],
                                  'duration':{'kind':'instant'}}}})
        b['actor_template']['action_ids'].append(sid)
        sealed_native_attack(bundles[2], 'Destroy review formation', count=1,sides=2,modifier=500,attack_bonus=100)
        for summon in bundles[0]['summons']:
            for action in summon['action_catalog']:
                action['parameters']['typed']['numbers']['attack_bonus']=100
        reseal(bundles)
    combat, table, mid = fixture(tmp_path, ['TAL_DEATH_GRAVE_FORMATION'], owner_bundle=commander_bundle(),
        bundle_transform=transform, foe_position={'x':5,'y':5}, ally_position={'x':3,'y':5})
    direct(combat, mid, 'Set review scenario')
    engine=reload(tmp_path,mid); aid=servant(engine,'grave_formation').entity_id
    assert any(c.condition_id=='condition:typed.'+condition for c in engine.state.actors[aid].conditions.values())
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Destroy review formation',target=aid).candidate_id,
        choices={'choice:needle.black_lantern_last_assault':[FOE]})
    engine=reload(tmp_path,mid)
    assert not any(p['context']['reaction_source_id']=='choice:needle.black_lantern_last_assault' for p in prompts)
    assert not any(c.condition_id==LAST_ASSAULT for c in engine.state.actors[OWNER].conditions.values())
    assert not engine.state.actors[aid].active and engine.state.actors[aid].summon['status']=='destroyed'
    assert not any(e.event_type=='ATTACK_ROLLED' and e.actor_id==aid for e in engine.events)
    turn(table,mid,OWNER); direct(combat,mid,'Supply review successor')
    engine=reload(tmp_path,mid)
    assert engine.state.actors[aid].active and engine.state.actors[aid].current_hp==165
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Destroy review formation',target=aid).candidate_id,
        choices={'choice:needle.black_lantern_last_assault':[FOE]})
    engine=reload(tmp_path,mid)
    assert any(c.condition_id==LAST_ASSAULT for c in engine.state.actors[OWNER].conditions.values())
    assert len([e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==aid])==1
    assert not engine.state.actors[aid].active


@pytest.mark.parametrize('commander',[False,True])
def test_off_turn_player_choice_names_packet_action_and_affected(tmp_path, commander):
    name='Destroy prompt formation' if commander else 'Guard prompt attack'
    def transform(bundles):
        sealed_native_attack(bundles[2],name,count=1,sides=2,modifier=500 if commander else 0,attack_bonus=100)
        for bundle, display in zip(bundles, ('Death caster','Protected companion','Raider')):
            bundle['actor_template']['display_name']=display
        reseal(bundles)
    talents=['TAL_DEATH_GRAVE_FORMATION'] if commander else ['TAL_DEATH_CORPSE_SERVANT','TAL_DEATH_DEATHLESS_GUARD']
    combat, _, mid = fixture(tmp_path,talents,owner_bundle=commander_bundle() if commander else None,
        owner_plan=None if commander else {'counts':{'corpse_servant':1,'lesser_corpse_servant':0}},
        bundle_transform=transform,foe_position={'x':5,'y':5} if commander else {'x':3,'y':5},
        ally_position={'x':3,'y':5} if commander else {'x':2,'y':6})
    table=recording_table(combat,tmp_path)
    if not commander:
        settle(table,mid,candidate(combat,mid,'Command Death servants').candidate_id)
    engine=reload(tmp_path,mid); aid=servant(engine,'grave_formation' if commander else 'corpse_servant').entity_id
    if not commander:
        turn(table,mid,aid); direct(combat,mid,'Guard')
    turn(table,mid,FOE)
    target=aid if commander else ALLY
    c=candidate(combat,mid,name,target=target)
    rid='choice:needle.black_lantern_last_assault' if commander else 'choice:needle.death_guard_step'
    prompts=settle(table,mid,c.candidate_id,choices={rid:None,'reaction:typed.TAL_DEATH_DEATHLESS_GUARD':'first'})
    engine=reload(tmp_path,mid)
    prompt=next(p for p in prompts if p['context']['reaction_source_id']==rid)
    context=next(c for c in table.contexts if c['reaction_source_id']==rid)['choice_trigger']
    assert context['source_definition_id']==c.source_definition_id
    assert context['action_name']==name and context['action_actor_id']==FOE
    assert context['affected_id']==target
    assert name in prompt['trigger']
    assert engine.state.actors[FOE].display_name in prompt['trigger']
    assert engine.state.actors[target].display_name in prompt['trigger']
    assert 'actor:' not in prompt['trigger'] and 'action:' not in prompt['trigger']
    (tmp_path/'prompt.json').write_text(json.dumps({'context':context,'rendered':prompt},indent=2))
    if commander:
        assert not any(c.condition_id==LAST_ASSAULT for c in engine.state.actors[OWNER].conditions.values())
    else:
        assert engine.state.actors[aid].reaction_available is False


def test_rotting_object_leaves_extra_attack_remainder_after_reload(tmp_path):
    from tests.test_auto21_weapons import BLADE, kit
    from combat.ext.special_attacks import FLAG, REST
    def transform(bundles):
        preparation({'object_material':'wood'})(bundles)
        for a in bundles[0]['action_catalog']:
            data=a.get('parameters',{}).get('typed',{})
            if data.get('source')=='TAL_DEATH_ROTTING_GRASP':
                data['numbers']['attack_bonus']=100
        reseal(bundles)
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_ROTTING_GRASP',
        'tianxia.path.body_refining.feature.extra_attack'],cl=11,
        owner_kit=kit(BLADE),bundle_transform=transform,foe_position={'x':3,'y':5})
    direct(combat,mid,'Set servant scenario')
    before=reload(tmp_path,mid).state.actors[OWNER]
    qi=before.resources['resource:core.qi']
    settle(table,mid,candidate(combat,mid,'Rotting Grasp',target='object:death-second-decay').candidate_id,
        choices={'choice:needle.rotting_object_damage':['maximum']})
    engine=reload(tmp_path,mid)
    owner=engine.state.actors[OWNER]
    assert not owner.action_available and owner.turn_flags[FLAG]==2
    assert owner.resources['resource:core.qi']==qi-1
    for left in (1,0):
        live=combat._load_session(mid).engine
        c=next(c for c in live.legal_candidates()
               if c.target_ids==(FOE,) and live.action_catalog[c.source_definition_id].parameters.get(REST))
        settle(table,mid,c.candidate_id)
        engine=reload(tmp_path,mid)
        assert engine.state.actors[OWNER].turn_flags[FLAG]==left
        assert engine.state.actors[OWNER].resources['resource:core.qi']==qi-1
    assert not any(a and a.parameters.get(REST) for c in engine.legal_candidates()
                   if (a := engine.action_catalog.get(c.source_definition_id)))
