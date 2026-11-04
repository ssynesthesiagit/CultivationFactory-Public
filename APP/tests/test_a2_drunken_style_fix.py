"""Fix-round regressions through committed service intents and cold replay."""
import copy
import json
import pytest
from tests.test_a2_drunken_style import (LEFT, RIGHT, act, fight, reload, resolve, _pin, cast, setup,
    STRIKE, MARK, BROKEN, WRONG, BEAT, SLIP, MOMENTUM, FOCUS, SWAY, AFTERIMAGE, IMAGE, turn)
from tests.auto_worker1_support import settle, action_sender

EXTRA = 'tianxia.path.body_refining.feature.extra_attack'
WRONG_CHOICE = 'choice:needle.drunken_wrong_hand'


def scores(monkeypatch, dex=18, strength=14):
    import tests.auto_worker1_support as fixture
    original = fixture.sheet
    def changed(*args, **kwargs):
        doc = original(*args, **kwargs)
        for row in doc['ability_scores_and_statistics']['abilities']:
            value = dex if row['ability'] == 'DEX' else strength if row['ability'] == 'STR' else row['score']
            row.update(score=value, modifier=(value-10)//2)
        return doc
    monkeypatch.setattr(fixture, 'sheet', changed)


def kit(item):
    return {'items':[{'item_id':'tianxia.mortal.weapon.'+item,
                     'name':{'fu':'Fu (Short Axe)', 'bi_shou':'Bi Shou (Dagger)'}[item], 'quantity':1}]}


def cold(c, m, prompts):
    with (c.userdata_root/'fix-prompts.ndjson').open('a') as out:
        out.write(json.dumps(prompts)+'\n')
    e = reload(c,m)
    assert c._load_session(m).verify()['status'] == 'PASS'
    return e


@pytest.mark.parametrize('abilities', [('DEX','STR'), ('STR','DEX')])
def test_extra_attack_ability_and_style_allocation_are_per_strike(tmp_path, monkeypatch, abilities):
    scores(monkeypatch)
    c,t,m = fight(tmp_path, [BROKEN,WRONG,SLIP,EXTRA], left_kit=kit('fu'), cl=5, prepare=[MARK], bundle_edit=_pin(save_dc=100))
    cast(c,t,m,'Prepare',target_id=RIGHT)
    label = 'Broken-Rhythm Strike: Fu (Short Axe)'
    before = next(a for a in reload(c,m).action_catalog.values() if a.owner_id==LEFT and a.display_name==label)
    sealed = copy.deepcopy(before.parameters)
    assert sealed['typed']['effects'][0]['count'] == 2
    old_damage = sealed['typed']['weapon']['damage']['modifier']
    picks = iter(abilities)
    def choose(prompt):
        key = prompt['context']['reaction_source_id']
        if key == WRONG_CHOICE: return [next(picks)]
        if key == 'choice:needle.drunken_slipping_palm': return ['prone']
        return [prompt['choice']['options'][0]['id']]
    result, prompts = settle(lambda answers:act(t,m,label,answers,target_id=RIGHT), choose=choose)
    assert result['status']=='COMMITTED'
    e = cold(c,m,prompts)
    assert len([p for p in prompts if p['context']['reaction_source_id']==WRONG_CHOICE]) == 2
    assert [r.modifier for r in e.rolls if r.actor_id==LEFT and r.reason.startswith('ATTACK:')]==[100+(2 if a=='DEX' else 0) for a in abilities]
    assert [r.modifier for r in e.rolls if r.actor_id==LEFT and r.reason.startswith('DAMAGE:')]==[old_damage+(2 if a=='DEX' else 0) for a in abilities]
    assert len([r for r in e.rolls if r.actor_id==RIGHT and r.reason.startswith('SAVE:')]) == 1
    assert any(v.condition_id=='condition:typed.prone' for v in e.state.actors[RIGHT].conditions.values())
    assert e.action_catalog[before.source_definition_id].parameters == sealed
    asked=[p for p in prompts if p['context']['reaction_source_id']==WRONG_CHOICE]
    assert 'attack 1 of 2' in json.dumps(asked[0]) and 'attack 2 of 2' in json.dumps(asked[1])


@pytest.mark.parametrize('original,chosen', [('DEX','STR'), ('STR','DEX')])
@pytest.mark.parametrize('talent', [BEAT,SLIP,MOMENTUM])
def test_finesse_ordinary_ability_keeps_hit_rider_slot(tmp_path, monkeypatch, original, chosen, talent):
    scores(monkeypatch, dex=18 if original=='DEX' else 14, strength=18 if original=='STR' else 14)
    c,t,m = fight(tmp_path,[BROKEN,WRONG,talent],left_kit=kit('bi_shou'),prepare=[MARK],bundle_edit=_pin(save_dc=100))
    cast(c,t,m,'Prepare',target_id=RIGHT)
    label='Broken-Rhythm Strike: Bi Shou (Dagger)'
    before=next(a for a in reload(c,m).action_catalog.values() if a.owner_id==LEFT and a.display_name==label)
    assert before.parameters['typed']['weapon']['ability']==original
    e,p = cast(c,t,m,label,{WRONG_CHOICE:[chosen], 'choice:needle.drunken_slipping_palm':['prone'],
                          'choice:needle.drunken_borrowed_momentum':['cell:5,6']},target_id=RIGHT)
    cold(c,m,p)
    assert any(v['context']['reaction_source_id'].endswith('_use') for v in p)
    if talent==MOMENTUM: assert e.state.actors[RIGHT].position.x==5
    else: assert len([v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT])==1
    assert e.state.actors[LEFT].resources[FOCUS]==(0 if talent==BEAT else 1)
    attack=next(r for r in e.rolls if r.actor_id==LEFT and r.reason.startswith('ATTACK:'))
    damage=next(r for r in e.rolls if r.actor_id==LEFT and r.reason.startswith('DAMAGE:'))
    assert attack.modifier==98
    assert damage.modifier==before.parameters['typed']['weapon']['damage']['modifier']-2


@pytest.mark.parametrize('talent,word', [(BEAT,'Wisdom saving throw'),(SLIP,'Dexterity saving throw'),(MOMENTUM,'5 feet')])
def test_hit_rider_prompt_names_action_and_actual_outcome(tmp_path,talent,word):
    c,t,m=setup(tmp_path,talent) if talent!=MOMENTUM else fight(tmp_path,[BROKEN,talent],prepare=[MARK],bundle_edit=_pin())
    if talent==MOMENTUM: cast(c,t,m,'Prepare',target_id=RIGHT)
    e,p=cast(c,t,m,STRIKE,{'choice:needle.drunken_borrowed_momentum':['cell:5,6']},target_id=RIGHT)
    cold(c,m,p)
    uses=[v for v in p if v['context']['reaction_source_id'].endswith('_use')]
    assert uses
    for prompt in uses:
        assert prompt['action']==STRIKE
        assert STRIKE in prompt['moment']
        assert word in prompt['choice']['options'][0]['label']
        assert 'printed' not in prompt['choice']['options'][0]['label']
    for prompt in p:
        if 'drunken_' in prompt['context']['reaction_source_id']:
            assert prompt['action']==STRIKE and STRIKE in prompt['moment']
    if talent==MOMENTUM:
        dest=next(v for v in p if v['context']['reaction_source_id']=='choice:needle.drunken_borrowed_momentum')
        assert dest['action']==STRIKE and STRIKE in dest['moment']


def test_afterimage_label_explains_expiry_during_ai_attack(tmp_path):
    def pin(bundle):
        if bundle['actor_id']==RIGHT:
            for a in bundle['action_catalog']:
                a.get('parameters',{}).get('typed',{}).setdefault('numbers',{})['attack_bonus']=-100
    c,t,m=fight(tmp_path,[SWAY,AFTERIMAGE],prepare=[MARK],cause=[{'type':'attack','attack_kind':'cultivation_ranged','count':1,'no_damage':True}],bundle_edit=pin)
    cast(c,t,m,'Prepare',target_id=RIGHT)
    turn(t,m,RIGHT)
    result,p=resolve(action_sender(c,t,m,'Cause',ai=True,target_id=LEFT),{'choice:needle.drunken_swaying_step':[]})
    assert result['status']=='COMMITTED'
    e=cold(c,m,p)
    assert any(v['context']['reactor_id']==LEFT for v in p)
    held=next(v for v in e.state.actors[LEFT].conditions.values() if v.condition_id==IMAGE)
    assert 'start of Keeper' in held.data['label'] and 'next turn' in held.data['label']


def test_player_hit_rider_during_ai_turn_names_counter_attack(tmp_path):
    counter='TAL_IRON_FIST_COUNTER_PALM'
    def pin(bundle):
        if bundle['actor_id']==LEFT:
            bundle['actor_template']['armor_class']=100
            # A sealed service fixture carries the actually compiled owned hit
            # rider into a nested attack, to exercise display/choice ownership.
            # This does not claim compiler-wide reaction modifier propagation.
            strike=next(a for a in bundle['action_catalog'] if '.natural.' in a['source_definition_id']
                        and a['parameters']['typed']['effects'][0]['type']=='attack')
            gates=[copy.deepcopy(e) for e in strike['parameters']['typed']['effects'][0].get('on_hit',[])
                   if e.get('type')=='if_marked' and e.get('at')=='hit']
            assert gates
            reaction=next(r for r in bundle['typed_reactions'] if r.get('feature_id')==counter)
            attack=next(e for e in reaction['effects'] if e.get('type')=='attack')
            attack.setdefault('on_hit',[]).extend(gates)
        for a in bundle['action_catalog']:
            typed=a.get('parameters',{}).get('typed',{})
            typed.setdefault('numbers',{})['attack_bonus']=100 if bundle['actor_id']==LEFT else -100
    c,t,m=fight(tmp_path,[MOMENTUM,counter,'tianxia.path.body_refining.feature.iron_fist'],prepare=[MARK],
        cause=[{'type':'attack','attack_kind':'unarmed','count':1,'no_damage':True}],bundle_edit=pin)
    cast(c,t,m,'Prepare',target_id=RIGHT)
    turn(t,m,RIGHT)
    result,p=resolve(action_sender(c,t,m,'Cause',ai=True,target_id=LEFT),
        {'choice:needle.iron_fist_damage_type':['BLUDGEONING'],
         'choice:needle.drunken_borrowed_momentum':['cell:5,6']})
    assert result['status']=='COMMITTED'
    e=cold(c,m,p)
    use=next(v for v in p if v['context']['reaction_source_id']=='choice:needle.drunken_borrowed_momentum_use')
    assert use['context']['reactor_id']==LEFT
    assert use['action']=='Counter Palm' and 'Counter Palm' in use['moment']
    assert '5 feet' in use['choice']['options'][0]['label']
    assert e.state.actors[RIGHT].position.x==5
