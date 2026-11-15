"""Space disappearance through saved CombatService table transactions/replay."""
import pytest
from tests.test_hunt32_edge import OWNER, FOE, act, match, reload
from combat.ext.spatial_absence import absent, ABSENT, RETURN
from tests.h1_support import ROOT

PRISON = 'tianxia.talent.space.fold_prison'
EXILE = 'tianxia.talent.space.exile_beyond_the_horizon'
VOID = 'tianxia.talent.space.void_between_worlds'
ALLY = 'actor:factory.h32-ally'


def _advance(table, mid):
    assert act(table, mid)['status'] == 'COMMITTED'


@pytest.mark.parametrize('mid,label', [(PRISON, 'Fold Prison'), (EXILE, 'Exile Beyond the Horizon'), (VOID, 'Void Between Worlds')])
def test_absence_failure_removes_body_and_outside_effects_after_reload(tmp_path, mid, label):
    combat, table, fight = match(tmp_path, [mid], allies=True, positions={OWNER:{"x":3,"y":6},ALLY:{"x":3,"y":7},FOE:{"x":4,"y":6}}, setup_actions=[{
        'name':'Outside damage', 'target':'ANY_CREATURE',
        'effects':[{'type':'damage','applies_to':'target','flat':7,'damage_types':['force']}]}])
    before = reload(combat, tmp_path, fight)
    home = before.state.actors[FOE].position
    hp = before.state.actors[FOE].current_hp
    assert act(table, fight, label, FOE)['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, fight)
    target = engine.state.actors[FOE]
    assert absent(target)
    absence=next(c for c in target.conditions.values() if c.condition_id==ABSENT)
    returned=next(c for c in target.conditions.values() if c.condition_id==RETURN)
    assert label in absence.data['label'] and ('turn' in absence.data['label'].lower() or 'minute' in absence.data['label'].lower())
    assert label in returned.data['label'] and ('turn' in returned.data['label'].lower() or 'minute' in returned.data['label'].lower())
    assert target.active and target.current_hp == hp
    assert (home.x, home.y) not in engine._occupied_cells_except(OWNER)
    from combat.target_knowledge import knowledge
    from combat import senses
    assert knowledge(engine, engine.state.actors[OWNER], target) is None
    assert knowledge(engine, target, engine.state.actors[OWNER]) is None
    assert not senses.perceives(engine, target, engine.state.actors[OWNER])
    # No native or typed hostile/friendly targeting of the absent body.
    assert not any(FOE in c.target_ids for c in engine.legal_candidates())
    _advance(table, fight)  # ally; can still attack the caster's original enemy side
    engine = reload(combat, tmp_path, fight)
    assert not any(FOE in c.target_ids for c in engine.legal_candidates())
    _advance(table, fight)  # absent foe's actual initiative slot still occurs
    engine = reload(combat, tmp_path, fight)
    assert engine.state.current_actor_id == FOE
    assert not any(c.kind == 'MOVE' or (c.kind in {'ACTION','BONUS_ACTION'} and c.target_ids != (FOE,)) for c in engine.legal_candidates())
    assert not any(e.event_type == 'GM_RIDER' and ('fold_prison' in str(e.source_definition_id) or 'exile_beyond' in str(e.source_definition_id)) for e in engine.events)


@pytest.mark.parametrize('mid,label', [(PRISON, 'Fold Prison'), (EXILE, 'Exile Beyond the Horizon')])
def test_success_returns_at_target_start_without_incapacitation(tmp_path, mid, label):
    combat, table, fight = match(tmp_path, [mid], setup_actions=[{
        'name':'Successful Charisma save', 'target':'ANY_CREATURE',
        'effects':[{'type':'save_bonus','amount':100,'abilities':['CHA'], 'applies_to':'target','expires_on':'UNTIL_REMOVED'}]}])
    assert act(table, fight, 'Successful Charisma save', FOE)['status'] == 'COMMITTED'
    assert act(table, fight, label, FOE)['status'] == 'COMMITTED'
    assert absent(reload(combat, tmp_path, fight).state.actors[FOE])
    _advance(table, fight)
    engine=reload(combat, tmp_path, fight)
    assert not absent(engine.state.actors[FOE])
    assert any(c.kind == 'ACTION' for c in engine.legal_candidates())


@pytest.mark.parametrize('mid,label', [(PRISON, 'Fold Prison'), (EXILE, 'Exile Beyond the Horizon')])
@pytest.mark.parametrize('z',[0,2])
def test_concentration_loss_returns_and_occupied_origin_uses_nearest_open(tmp_path, mid, label, z):
    combat, table, fight = match(tmp_path, [mid], allies=True, positions={OWNER:{"x":3,"y":6,"z":z},ALLY:{"x":3,"y":7,"z":z},FOE:{"x":4,"y":6,"z":z}}, setup_actions=[{
        'name':'Break concentration', 'effects':[{'type':'damage','applies_to':'self','flat':50,'damage_types':['force']}]}])
    assert act(table, fight, label, FOE)['status'] == 'COMMITTED'
    engine=reload(combat,tmp_path,fight)
    home=engine.state.actors[FOE].position
    _advance(table,fight)
    state=table.state(fight);menu=state['menu']
    move=next(m for m in menu['moves'] if m['destination'].get('x')==home.x
              and m['destination'].get('y')==home.y and m['destination'].get('z',0)==home.z)
    assert table.act(fight,move['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'])['status']=='COMMITTED'
    reload(combat,tmp_path,fight)
    _advance(table,fight)
    _advance(table,fight)
    assert act(table,fight,'Break concentration')['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    target=engine.state.actors[FOE]
    assert not absent(target)
    assert target.position != home
    assert engine.grid.distance_ft(home,target.position)==5
    assert engine.state.actors[ALLY].position==home


def test_void_delays_damage_to_casters_next_end_and_starts_minute_on_return(tmp_path):
    combat,table,fight=match(tmp_path,[VOID])
    hp=reload(combat,tmp_path,fight).state.actors[FOE].current_hp
    assert act(table,fight,'Void Between Worlds',FOE)['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    assert engine.state.actors[FOE].current_hp==hp
    _advance(table,fight)
    _advance(table,fight)
    engine=reload(combat,tmp_path,fight)
    assert engine.state.current_actor_id==OWNER
    assert absent(engine.state.actors[FOE])
    _advance(table,fight)
    engine=reload(combat,tmp_path,fight)
    target=engine.state.actors[FOE]
    assert not absent(target)
    rolls=[e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and 'void_between_worlds' in str(e.source_definition_id)]
    assert len(rolls)==1 and rolls[0].payload['expression']=='8d10+0'
    assert target.current_hp < hp
    assert any(c.condition_id=='condition:typed.cannot_teleport' for c in target.conditions.values())


def test_void_return_consequence_resolves_while_original_caster_is_absent(tmp_path):
    exile = {'type':'spatial_absence','applies_to':'target','expires_on':'END_OF_SOURCE_NEXT_TURN'}
    combat,table,fight=match(tmp_path,[VOID],allies=True,ally_setup_actions=[{
        'name':'Exile the caster','target':'ANY_CREATURE','economy':'ACTION','effects':[exile]}])
    hp=reload(combat,tmp_path,fight).state.actors[FOE].current_hp
    assert act(table,fight,'Void Between Worlds',FOE)['status']=='COMMITTED'
    _advance(table,fight)  # the foe exiles the original caster
    assert table.state(fight)['menu'].get('actor_id') == ALLY, table.state(fight)['menu']
    assert any(g['label']=='Exile the caster' for g in table.state(fight)['menu']['actions']), table.state(fight)['menu']['actions']
    assert act(table,fight,'Exile the caster',OWNER)['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    assert absent(engine.state.actors[OWNER])
    _advance(table,fight)  # Void victim's absent slot
    _advance(table,fight)  # original caster's absent turn starts
    _advance(table,fight)  # absent caster's turn ends; Void's stored effect resolves
    engine=reload(combat,tmp_path,fight)
    target=engine.state.actors[FOE]
    assert not absent(target)
    rolls=[e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and 'void_between_worlds' in str(e.source_definition_id)]
    assert len(rolls)==1 and rolls[0].payload['expression']=='8d10+0'
    assert target.current_hp < hp
    assert any(c.condition_id=='condition:typed.cannot_teleport' for c in target.conditions.values())


@pytest.mark.parametrize('mid,label',[(PRISON,'Fold Prison'),(EXILE,'Exile Beyond the Horizon'),(VOID,'Void Between Worlds')])
def test_ai_harms_enemy_with_ally_and_enemy_in_range(tmp_path,mid,label):
    combat,table,fight=match(tmp_path,[mid],mode='LOCAL_AUTO',allies=True,ally_mode='LOCAL_AUTO', positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':4,'y':6}})
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary
    from combat.gate4_context import build_decision_context
    table.state(fight)
    session=combat._load_session(fight)
    action=next(a for a in session.engine.action_catalog.values()
                if a.owner_id==OWNER and a.parameters.get('typed',{}).get('source')==mid)
    policy,_=PolicyLibrary(ROOT).for_actor(OWNER)
    # The fixture tells the AI which technique to practice. It still chooses
    # among the FULL ordinary legal roster/recipient list with its real policy.
    policy=policy.model_copy(update={'action_priorities':{action.source_definition_id:200}})
    choice=LocalDeterministicController().choose_primary_action(build_decision_context(session.engine,policy,for_ai=True))
    selected=next(c for c in session.engine.legal_candidates() if c.candidate_id==choice.intent.candidate_id)
    assert selected.source_definition_id==action.source_definition_id
    assert selected.target_ids==(FOE,)
    session.submit_intent(choice.intent,primary_decision_record=choice.record,reaction_provider=None)
    engine=reload(combat,tmp_path,fight)
    assert absent(engine.state.actors[FOE])
    assert not absent(engine.state.actors[ALLY])
    assert not absent(engine.state.actors[OWNER])

ANCHOR='insight.anchored-soul'
DISPLACE='tianxia.talent.space.spatial_displacement'


def _answered_action(table,fight,label,target,*,returning=True):
    state=table.state(fight);menu=state['menu']
    group=next(g for g in menu['actions'] if g['label']==label)
    option=next(o for o in group['options'] if target in o.get('target_ids',[]))
    args=(option['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'])
    answers=[];prompts=[]
    result=table.act(fight,*args,answers)
    while result['status']=='REACTION_REQUIRED':
        prompt=result['reaction'];prompts.append(prompt)
        assert len(prompts)<8, result
        anchor='anchored_soul' in str(prompt['context'])
        answer={**prompt['context'],'selection':'USE' if not anchor or returning else 'DECLINE'}
        if answer['selection']=='USE' and prompt.get('choice'):
            answer['option_ids']=[prompt['choice']['options'][0]['id']]
        answers.append(answer)
        result=table.act(fight,*args,answers)
    assert result['status']=='COMMITTED'
    return prompts


@pytest.mark.parametrize('mode',['MANUAL','LOCAL_AUTO'])
@pytest.mark.parametrize('returning',[True,False])
def test_anchored_soul_advantage_optional_return_and_spent_allowance(tmp_path,mode,returning):
    combat,table,fight=match(tmp_path,[DISPLACE],foe_mids=[ANCHOR])
    # Synthetic foe still owns its actual feature; use recorded mode before
    # genesis rather than mutate a live actor. match() makes foes MANUAL.
    if mode=='LOCAL_AUTO':
        combat.set_controller_mode(fight,actor_id=FOE,controller_mode='LOCAL_AUTO')
    start=reload(combat,tmp_path,fight).state.actors[FOE].position
    prompts=_answered_action(table,fight,'Spatial Displacement',FOE,returning=returning)
    engine=reload(combat,tmp_path,fight)
    target=engine.state.actors[FOE]
    rolls=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'spatial_displacement' in str(e.source_definition_id)]
    assert rolls and rolls[-1].payload['mode']=='ADVANTAGE'
    use=mode=='LOCAL_AUTO' or returning
    assert (target.position==start)==use
    assert target.reaction_available
    assert any(c.condition_id=='condition:typed.anchored_soul_used' for c in target.conditions.values())==use
    assert any('anchored_soul' in str(p['context']) for p in prompts)==(mode=='MANUAL')


def test_anchored_soul_does_not_grant_advantage_to_ordinary_save(tmp_path):
    combat,table,fight=match(tmp_path,['tianxia.talent.space.spatial_severance'],foe_mids=[ANCHOR])
    assert act(table,fight,'Spatial Severance',FOE)['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    rolls=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'spatial_severance' in str(e.source_definition_id)]
    assert rolls and rolls[-1].payload['mode']=='NORMAL'


def test_anchored_soul_advantage_is_scoped_to_the_spatial_save_in_a_multi_save_action(tmp_path):
    saves=[
        {'type':'save','ability':'cha','on_fail':[{'type':'spatial_absence','applies_to':'target','expires_on':'END_OF_SOURCE_NEXT_TURN'}]},
        {'type':'save','ability':'wis','on_fail':[{'type':'condition','condition':'frightened','applies_to':'target'}]},
    ]
    combat,table,fight=match(tmp_path,[DISPLACE],foe_mids=[ANCHOR],setup_actions=[{
        'name':'Two differently scoped saves','target':'ANY_CREATURE','effects':saves,
        'typed':{'numbers':{'save_dc':1}}}])
    assert act(table,fight,'Two differently scoped saves',FOE)['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    rolls=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'setup' in str(e.source_definition_id)]
    assert [r.payload['mode'] for r in rolls]==['ADVANTAGE','NORMAL']


def test_explicit_willing_transport_does_not_prompt_or_spend_anchored_soul(tmp_path):
    combat,table,fight=match(tmp_path,[DISPLACE],foe_mids=[ANCHOR],setup_actions=[{
        'name':'Willing teleport','target':'ANY_CREATURE','effects':[{'type':'teleport','applies_to':'target',
            'distance_ft':20,'unwilling':False,'choose_subject_destination':True}]}])
    prompts=_answered_action(table,fight,'Willing teleport',FOE)
    engine=reload(combat,tmp_path,fight)
    assert not any('anchored_soul' in str(p.get('context')) for p in prompts)
    assert not any(c.condition_id=='condition:typed.anchored_soul_used' for c in engine.state.actors[FOE].conditions.values())


def test_ai_spatial_action_pauses_for_manual_anchored_soul_owner(tmp_path):
    combat,table,fight=match(tmp_path,[DISPLACE],mode='LOCAL_AUTO',foe_mids=[ANCHOR])
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary
    from combat.gate4_context import build_decision_context
    table.state(fight)
    session=combat._load_session(fight)
    action=next(a for a in session.engine.action_catalog.values()
                if a.owner_id==OWNER and a.parameters.get('typed',{}).get('source')==DISPLACE)
    policy,_=PolicyLibrary(ROOT).for_actor(OWNER)
    policy=policy.model_copy(update={'action_priorities':{action.source_definition_id:200}})
    choice=LocalDeterministicController().choose_primary_action(build_decision_context(session.engine,policy,for_ai=True))
    assert next(c for c in session.engine.legal_candidates() if c.candidate_id==choice.intent.candidate_id).target_ids==(FOE,)
    class FixedController:
        def choose_primary_action(self, context):
            return choice
        def choose_reaction(self, context):
            return LocalDeterministicController().choose_reaction(context)
    combat.controller=FixedController()
    result=table.auto_step(fight,table.state(fight)['last_sequence'])
    assert result['status']=='REACTION_REQUIRED'
    assert result['reaction']['context']['reactor_id']==FOE
    assert 'anchored_soul' in str(result['reaction']['context'])
    engine=reload(combat,tmp_path,fight)
    assert not any(c.condition_id=='condition:typed.anchored_soul_used' for c in engine.state.actors[FOE].conditions.values())

@pytest.mark.parametrize('mid,label',[(PRISON,'Fold Prison'),(EXILE,'Exile Beyond the Horizon')])
def test_concentration_damage_releases_before_target_turn(tmp_path,mid,label):
    combat,table,fight=match(tmp_path,[mid], setup_actions=[{
        'name':'Break concentration','effects':[{'type':'damage','applies_to':'self','flat':50,'damage_types':['force']}]}])
    assert act(table,fight,label,FOE)['status']=='COMMITTED'
    assert absent(reload(combat,tmp_path,fight).state.actors[FOE])
    assert act(table,fight,'Break concentration')['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    assert not absent(engine.state.actors[FOE])
    assert engine.state.actors[OWNER].concentration is None


@pytest.mark.parametrize('save_dc,success',[ (100,False), (1,True) ])
def test_self_target_absence_shared_provider_returns_exact_instance(
        tmp_path, save_dc, success):
    prison_row={'type':'spatial_absence','applies_to':'self','incapacitated':True,
        'expires_on':'START_OF_TARGET_NEXT_TURN','end_concentration_on_return':True}
    setup = [{'name':'Self-target absence lifecycle','target':'SELF','typed':{
        'duration':{'kind':'concentration','concentration':True},'numbers':{'save_dc':save_dc}},'effects':[{
                'type':'save','ability':'cha','dc':save_dc,'applies_to':'self',
                'on_fail':[dict(prison_row)],'on_success':[dict(prison_row)]}]}]
    # Keep one compiled Space feature on the synthetic fixture so the normal
    # typed-service path is active; the sealed self-target action exercises the
    # same provider row independently of an ability-specific branch.
    combat,table,fight=match(tmp_path,[PRISON],setup_actions=setup)
    assert act(table,fight,'Self-target absence lifecycle',OWNER)['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER
           and 'dc' in e.payload]
    assert len(saves)==1, [(e.event_type,e.source_definition_id,e.payload) for e in engine.events[-20:]]
    assert saves[0].payload['success'] is success
    actor=engine.state.actors[OWNER]
    assert not absent(actor)
    assert not any(c.condition_id in (ABSENT,RETURN) for c in actor.conditions.values())
    applied=[e for e in engine.events if e.event_type=='CONDITION_APPLIED'
             and e.payload.get('condition_id')==ABSENT]
    removed=[e for e in engine.events if e.event_type=='CONDITION_REMOVED'
             and e.payload.get('condition_id')==ABSENT]
    assert len(applied)==len(removed)==1
    assert removed[0].payload['instance_id']==applied[0].payload['instance_id']
    assert removed[0].payload['reason']=='CONCENTRATION_ENDED_DURING_APPLICATION'
    assert actor.concentration is None


@pytest.mark.parametrize('bonus,kept', [(100, True), (-100, False)])
def test_void_preserves_victim_concentration_until_return_damage(tmp_path, bonus, kept):
    combat,table,fight=match(tmp_path,[VOID],foe_setup_actions=[{
        'name':'Victim concentration','typed':{'duration':{'kind':'concentration','concentration':True}},
        'effects':[{'type':'save_bonus','amount':bonus,'abilities':['CON'],
                    'applies_to':'self','expires_on':'UNTIL_REMOVED'}]}])
    _advance(table,fight)
    assert act(table,fight,'Victim concentration')['status']=='COMMITTED'
    victim=reload(combat,tmp_path,fight).state.actors[FOE]
    held=victim.concentration.model_dump(mode='json')
    _advance(table,fight)
    assert act(table,fight,'Void Between Worlds',FOE)['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    victim=engine.state.actors[FOE]
    assert absent(victim)
    assert victim.concentration is not None
    assert victim.concentration.model_dump(mode='json')==held
    assert not any(e.event_type=='CONCENTRATION_ENDED' and e.actor_id==FOE for e in engine.events)
    _advance(table,fight)
    _advance(table,fight)
    _advance(table,fight)
    engine=reload(combat,tmp_path,fight)
    victim=engine.state.actors[FOE]
    assert not absent(victim)
    checks=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==FOE
            and e.source_definition_id=='system:combat.concentration']
    assert len(checks)==1 and checks[0].payload['success'] is kept
    assert (victim.concentration is not None) is kept
    assert any(e.event_type=='DAMAGE_ROLLED' and 'void_between_worlds' in str(e.source_definition_id) for e in engine.events)


def test_anchored_soul_exile_initial_and_repeat_advantage_after_reload(tmp_path):
    combat,table,fight=match(tmp_path,[EXILE],foe_mids=[ANCHOR])
    assert act(table,fight,'Exile Beyond the Horizon',FOE)['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    assert absent(engine.state.actors[FOE])
    rolls=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'exile_beyond' in str(e.source_definition_id)]
    assert len(rolls)==1 and rolls[0].payload['mode']=='ADVANTAGE'
    _advance(table,fight)
    reload(combat,tmp_path,fight)
    _advance(table,fight)
    engine=reload(combat,tmp_path,fight)
    rolls=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'exile_beyond' in str(e.source_definition_id)]
    assert len(rolls)==2 and rolls[1].payload['mode']=='ADVANTAGE'


def test_anchored_soul_unrelated_repeat_save_remains_normal(tmp_path):
    combat,table,fight=match(tmp_path,[EXILE],foe_mids=[ANCHOR],setup_actions=[{
        'name':'Ordinary repeated fear','target':'ANY_CREATURE',
        'typed':{'numbers':{'save_dc':40}},'effects':[{'type':'save','ability':'wis',
            'on_fail':[{'type':'condition','condition':'frightened','applies_to':'target',
                        'expires_on':'UNTIL_REMOVED','repeat_save':{'ability':'WIS','when':'end'}}]}]}])
    assert act(table,fight,'Ordinary repeated fear',FOE)['status']=='COMMITTED'
    reload(combat,tmp_path,fight)
    _advance(table,fight)
    _advance(table,fight)
    engine=reload(combat,tmp_path,fight)
    rolls=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'setup' in str(e.source_definition_id)]
    assert len(rolls)==2 and [r.payload['mode'] for r in rolls]==['NORMAL','NORMAL']


def test_exile_labels_include_one_minute_cap_repeat_and_concentration(tmp_path):
    combat,table,fight=match(tmp_path,[EXILE])
    assert act(table,fight,'Exile Beyond the Horizon',FOE)['status']=='COMMITTED'
    engine=reload(combat,tmp_path,fight)
    for condition in engine.state.actors[FOE].conditions.values():
        if condition.condition_id in (ABSENT,RETURN):
            label=condition.data['label']
            assert 'Exile Beyond the Horizon' in label
            assert 'up to 1 minute' in label
            assert 'CHA save repeated at the end of each of your turns' in label
            assert "caster's concentration ends" in label
