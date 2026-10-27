"""A2ASHr1 review regressions through session execution and cold replay."""
import json
from pathlib import Path
import pytest
from combat.gate4_adapters import ManualControllerAdapter
from tests.auto_worker1_support import fight, act, reload, settle, turn, LEFT, RIGHT, ALLY
from tests.test_a2_ash_service import COURT, WORLD, CLONE, P, cast


def armored(bundle):
    if bundle['actor_template']['entity_id']==ALLY:
        bundle['actor_template']['armor_class']=100
        # A real Action spent through the session, for the native one-activity veto.
        source='action:test.ash.spend'
        bundle['actor_template']['action_ids'].append(source)
        bundle['action_catalog'].append({'source_definition_id':source,'display_name':'Spend Action',
            'owner_id':ALLY,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'SELF',
            'range_ft':0,'costs':[],'parameters':{'typed':{'effects':[], 'numbers':{},'riders':[]}}})
        bundle['typed_reactions']=[]
        bundle['typed_passives']=[]


def setup(tmp_path, *, prepare=()):
    c,t,m=fight(tmp_path,[COURT],cl=17,ally=[],bundle_edit=armored,prepare=prepare,prepare_target="ANY_CREATURE",
        cause=[{'type':'attack','attack_kind':'cultivation_ranged','on_hit':[]}])
    if prepare:settle(lambda a:act(t,m,'Prepare',a,target_id=ALLY))
    cast(c,t,m,COURT)
    return c,t,m


def miss_step(p):
    return 'field_miss_step' in p['context']['reaction_source_id']


def moving(p):
    return [o['id'] for o in p['choice']['options'] if o['id']!='cell:3,5'][:1]


@pytest.mark.parametrize('restriction',['grappled','restrained','native_veto'])
def test_step_obeys_native_movement_restrictions(tmp_path,restriction):
    effects=([{'type':'creature_bar','applies_to':'target','bar':{'one_activity':True},
               'expires_on':'UNTIL_REMOVED','label':'Only one activity'}] if restriction=='native_veto' else
             [{'type':'condition','condition':restriction,'applies_to':'target','expires_on':'UNTIL_REMOVED'}])
    c,t,m=setup(tmp_path,prepare=effects)
    if restriction=='native_veto':
        turn(t,m,ALLY)
        settle(lambda a:act(t,m,'Spend Action',a))
    turn(t,m,RIGHT)
    before=reload(c,m);defender=before.state.actors[ALLY]
    if restriction=='native_veto':
        assert before._effective_speed(defender)>0 and not defender.action_available
        from combat.ext.granted_movement import choices
        assert not choices(before,defender,5)
    else:assert before._effective_speed(defender)==0
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=ALLY),moving)
    e=reload(c,m)
    assert (e.state.actors[ALLY].position.x,e.state.actors[ALLY].position.y)==(3,5)
    assert not any(miss_step(p) for p in prompts)
    assert not any(v.event_type=='MOVEMENT_COMMITTED' and v.actor_id==ALLY for v in e.events)


def observed_attack(c):
    original=c.controller
    class Observed:
        def choose_primary_action(self,context):
            selected=next(row for row in context.legal_candidates
                          if row.display_name=='Cause' and row.target_ids==(ALLY,))
            return ManualControllerAdapter(lambda _:(selected.candidate_id,())).choose_primary_action(context)
        def __getattr__(self,name):return getattr(original,name)
    c.controller=Observed()


@pytest.mark.parametrize('mode,decline',[('MANUAL',False),('MANUAL',True),('LOCAL_AUTO',False)])
def test_real_ai_turn_respects_beneficiary_choice(tmp_path,mode,decline):
    c,t,m=setup(tmp_path)
    turn(t,m,RIGHT)
    e=reload(c,m)
    assert not e.typed_reaction_rows.get(ALLY)
    assert not any(r.get('choice_owner') for r in e.typed_passive_rows.get(ALLY,[]))
    c.set_controller_mode(m,actor_id=RIGHT,controller_mode='LOCAL_AUTO')
    c.set_controller_mode(m,actor_id=ALLY,controller_mode=mode)
    observed_attack(c)
    before=reload(c,m).state.actors[ALLY]
    pool=before.movement_remaining_ft
    resources=dict(before.resources)
    economy=(before.action_available,before.bonus_action_available,before.reaction_available)
    _,prompts=settle(lambda a:t.auto_step(m,t.state(m)['last_sequence'],a),
                     lambda p:[] if decline else moving(p))
    steps=[p for p in prompts if miss_step(p)]
    assert len(steps)==(1 if mode=='MANUAL' else 0)
    if steps:assert steps[0]['context']['reactor_id']==ALLY
    e=reload(c,m);defender=e.state.actors[ALLY]
    assert ((defender.position.x,defender.position.y)!=(3,5))== (not decline)
    assert defender.movement_remaining_ft==pool and defender.resources==resources
    assert (defender.action_available,defender.bonus_action_available,defender.reaction_available)==economy
    assert not any(v.event_type=='ATTACK_DECLARED' and 'opportunity' in v.source_definition_id for v in e.events)
    assert not any(v.event_type=='REACTION_USED' and v.actor_id==ALLY for v in e.events)
    moves=[v for v in e.events if v.event_type=='MOVEMENT_COMMITTED' and v.actor_id==ALLY]
    assert len(moves)==(0 if decline else 1)
    if moves:assert 'planned_cost_ft' in moves[0].payload and not moves[0].payload.get('forced')


def test_step_prompt_identifies_grant_trigger_target_and_free_cost(tmp_path):
    c,t,m=setup(tmp_path)
    turn(t,m,RIGHT)
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=ALLY),lambda p:[])
    p=next(p for p in prompts if miss_step(p))
    assert p['reaction']=='Court of the Last Ember'
    assert p['action']=='Cause' and p['trigger_actor']=='Visitor'
    assert p['affected']==p['by']==p['reactor']=='Visitor'
    assert 'no Action, Reaction or resource cost' in p['moment']
    assert 'misses' in p['moment'] and '5 feet' in p['moment']
    assert 'opportunity attacks' in p['moment']
    assert p['choice']['allow_decline']
    assert (reload(c,m).state.actors[ALLY].position.x,reload(c,m).state.actors[ALLY].position.y)==(3,5)


def test_reviewed_records_are_unique_and_generated_court_still_executes(tmp_path):
    c,t,m=setup(tmp_path)
    assert any(r.data.get('rule',{}).get('step_after_enemy_miss_ft') for r in reload(c,m).state.actors[ALLY].conditions.values())
    root=Path(__file__).resolve().parents[1]/'authority/typed_mechanics/reviewed_final.d'
    for source in (COURT,WORLD,CLONE,P+'ash_sovereign_incarnation',P+'rolling_ashfall'):
        files=[p.name for p in root.glob('*.json') if source in json.loads(p.read_text()).get('mechanics',{})]
        assert len(files)==1,(source,files)


@pytest.mark.parametrize('smothered',[False,True])
def test_court_concentration_disadvantage_requires_smothered(tmp_path,smothered):
    c,t,m=fight(tmp_path,[COURT],cl=17,right_talents=[P+'ash_form'],
        prepare=[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}])
    cast(c,t,m,COURT)
    turn(t,m,RIGHT,picks={'choice:needle.ash_court_outcome':['smothered' if smothered else 'damage']})
    settle(lambda a:act(t,m,'Ash Form',a))
    turn(t,m,LEFT)
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=reload(c,m)
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and v.source_definition_id=='system:combat.concentration']
    assert saves
    assert saves[-1].payload['mode']==('DISADVANTAGE' if smothered else 'NORMAL')


@pytest.mark.parametrize('damage_type',['FIRE','NECROTIC','PSYCHIC'])
def test_clone_cinder_strike_uses_unresisted_allowed_damage_type(tmp_path,damage_type):
    from tests.test_auto62_destruction import cell_sender
    c,t,m=fight(tmp_path,[CLONE],cl=17,left_attack_bonus=100,
        prepare=[{'type':'resistance','damage_types':[k for k in ('FIRE','NECROTIC','PSYCHIC') if k!=damage_type],
                  'applies_to':'target','expires_on':'UNTIL_REMOVED'}])
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    settle(cell_sender(c,t,m,'Ash Clone',(3,5),False))
    settle(lambda a:act(t,m,'Command Ash Clone',a))
    clone=next(a for a in reload(c,m).state.actors.values() if a.summon)
    turn(t,m,clone.entity_id)
    # Owner's shared damage rule chooses the best landing allowed type; the strike's list is sealed.
    def send(answers):
        state=t.state(m);menu=state['menu']
        candidates=c._load_session(m).engine.legal_candidates()
        selected=next(row for row in candidates if row.display_name=='Cinder Strike'
                      and row.target_ids==(RIGHT,))
        return t.act(m,selected.candidate_id,menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
    e=reload(c,m)
    action=next(a for a in e.action_catalog.values() if a.owner_id==clone.entity_id and a.display_name=='Cinder Strike')
    assert action.parameters['typed']['weapon']['damage_types']==['FIRE','NECROTIC','PSYCHIC']
    settle(send)
    e=reload(c,m)
    hits=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==clone.entity_id]
    assert hits and hits[-1].payload['damage_type']==damage_type
    assert e.state.actors[RIGHT].current_hp<1000
