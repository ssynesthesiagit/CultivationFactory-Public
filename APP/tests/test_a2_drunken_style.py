"""Printed post-save choices commit through table/session and cold replay."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, resolve
from tests.test_auto104_drunken_rhythms import _pin, STRIKE, _off_rhythm
from tests.hunt15_support import turn
BEAT='TAL_DRUNKEN_STYLE_PALM_OF_THE_MISSING_BEAT'
SLIP='TAL_DRUNKEN_STYLE_SLIPPING_PALM'
BROKEN='TAL_DRUNKEN_STYLE_BROKEN_RHYTHM_STRIKE'
FOCUS='resource:core.martial_focus'
USE_IDS={BEAT:'choice:needle.drunken_missing_beat_use',SLIP:'choice:needle.drunken_slipping_palm_use'}
MARK={'type':'mark','mark':'Off-Rhythm','applies_to':'target','duration':{'kind':'minutes','amount':1}}

def cast(c,t,m,label,picks=None,**kwargs):
    result,prompts=resolve(lambda answers:act(t,m,label,answers,**kwargs),picks)
    assert result['status']=='COMMITTED'
    import json
    with (c.userdata_root/'a2-prompts.ndjson').open('a') as capture:
        capture.write(json.dumps({'action':label,'prompts':prompts})+'\n')
    assert c._load_session(m).mechanical.replay()['status']=='PASS'
    return reload(c,m),prompts

def setup(tmp_path,talent,dc=100,marked=True):
    c,t,m=fight(tmp_path,[BROKEN,talent],prepare=[MARK] if marked else [],bundle_edit=_pin(save_dc=dc),right_talents=['TAL_DRUNKEN_STYLE_REELING_STEP'])
    if marked:cast(c,t,m,'Prepare',target_id=RIGHT)
    return c,t,m

@pytest.mark.parametrize('choice',['reaction','bonus','advantage','opportunity'])
def test_missing_beat_failed_save_chooses_exact_restriction_and_expiry(tmp_path,choice):
    c,t,m=setup(tmp_path,BEAT)
    before=reload(c,m).state.actors[LEFT].resources[FOCUS]
    e,prompts=cast(c,t,m,STRIKE,{'choice:needle.drunken_missing_beat':[choice]},target_id=RIGHT)
    asked=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.drunken_missing_beat')
    assert {o['id'] for o in asked['choice']['options']}=={'reaction','bonus','advantage','opportunity'}
    held=[v for v in e.state.actors[RIGHT].conditions.values() if v.condition_id=='condition:typed.drunken_missing_beat']
    assert len(held)==1 and held[0].data['beat']==choice and held[0].source_actor_id==LEFT
    assert held[0].expires_on=='START_OF_SOURCE_NEXT_TURN'
    assert held[0].data['bonus_turn']==e.state.actors[RIGHT].turns_started+1
    assert e.state.actors[LEFT].resources[FOCUS]==before-1
    assert not any(x.event_type=='GM_RIDER' for x in e.events)
    turn(t,m,RIGHT)
    e=reload(c,m)
    from combat import ext
    a=e.state.actors[RIGHT]
    bonus=next(x for x in e.action_catalog.values() if x.owner_id==RIGHT and str(getattr(x.economy,'value',x.economy))=='BONUS_ACTION')
    from combat.ext.drunken_rhythms import missing_bonus
    assert (missing_bonus(e,a,None,bonus) is False)==(choice=='bonus')
    assert (False in ext.run('opportunity_allowed',e,a,e.state.actors[LEFT]))==(choice=='opportunity')
    assert ('ADVANTAGE' in [v for result in ext.run('attack_mode_removed',e,a,e.state.actors[LEFT],False) if isinstance(result,list) for v in result])==(choice=='advantage')
    from combat.ext.reaction_eligibility import eligible
    assert eligible(e,a,a)==(choice!='reaction')
    labels=[g['label'] for g in t.state(m)['menu']['actions']]
    assert ('Reeling Step' in labels)==(choice!='bonus')
    turn(t,m,LEFT)
    assert not any(v.condition_id=='condition:typed.drunken_missing_beat' for v in reload(c,m).state.actors[RIGHT].conditions.values())

def test_missing_beat_success_bars_only_opportunity_attacks(tmp_path):
    c,t,m=setup(tmp_path,BEAT,-100)
    e,prompts=cast(c,t,m,STRIKE,target_id=RIGHT)
    held=next(v for v in e.state.actors[RIGHT].conditions.values() if v.condition_id=='condition:typed.drunken_missing_beat')
    assert held.data['beat']=='opportunity' and e.state.actors[RIGHT].reaction_available
    assert all(o['id']=='opportunity' for p in prompts if p['context']['reaction_source_id']=='choice:needle.drunken_missing_beat' for o in p['choice']['options'])

@pytest.mark.parametrize('failed,choice',[(True,'push'),(True,'prone'),(True,'step'),(False,'step')])
def test_slipping_palm_post_save_choice_moves_or_knocks_prone_once(tmp_path,failed,choice):
    c,t,m=setup(tmp_path,SLIP,100 if failed else -100)
    before=reload(c,m).state.actors
    e,prompts=cast(c,t,m,STRIKE,{'choice:needle.drunken_slipping_palm':[choice],'choice:needle.drunken_slipping_step':['cell:3,5']},target_id=RIGHT)
    asked=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.drunken_slipping_palm')
    assert {o['id'] for o in asked['choice']['options']}==({'push','prone','step'} if failed else {'step'})
    a,b=e.state.actors[LEFT],e.state.actors[RIGHT]
    assert any(v.condition_id=='condition:typed.prone' for v in b.conditions.values())==(choice=='prone')
    assert (b.position!=before[RIGHT].position)==(choice=='push')
    assert (a.position!=before[LEFT].position)==(choice=='step')
    if choice=='push':assert e.grid.distance_ft(b.position,before[RIGHT].position)==5
    assert a.movement_remaining_ft==before[LEFT].movement_remaining_ft
    assert len([v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT])==1
    assert not any(v.event_type=='GM_RIDER' for v in e.events)

@pytest.mark.parametrize('talent',[BEAT,SLIP])
def test_preexisting_off_rhythm_required_not_the_mark_from_this_hit(tmp_path,talent):
    c,t,m=setup(tmp_path,talent,marked=False)
    before=reload(c,m).state.actors[LEFT].resources[FOCUS]
    e,prompts=cast(c,t,m,STRIKE,target_id=RIGHT)
    assert _off_rhythm(e.state.actors[RIGHT])
    assert not [v for v in e.events if v.event_type=='SAVE_ROLLED']
    assert e.state.actors[LEFT].resources[FOCUS]==before
    assert not any('drunken_missing_beat' in str(p) or 'drunken_slipping_palm' in str(p) for p in prompts)

AFTERIMAGE='TAL_DRUNKEN_STYLE_AFTERIMAGE_SWAY'
SWAY='TAL_DRUNKEN_STYLE_SWAYING_GUARD'
IMAGE='condition:typed.drunken_afterimage'

@pytest.mark.parametrize('owned',[False,True])
def test_afterimage_follows_guarded_miss_and_is_spent_by_next_roll(tmp_path,owned):
    def pin(bundle):
        if bundle['actor_id']==RIGHT:
            for a in bundle['action_catalog']:
                a.get('parameters',{}).get('typed',{}).setdefault('numbers',{})['attack_bonus']=-100
    c,t,m=fight(tmp_path,[SWAY,*([AFTERIMAGE] if owned else [])],prepare=[MARK],
        cause=[{'type':'attack','attack_kind':'cultivation_ranged','count':1,'no_damage':True}],bundle_edit=pin)
    cast(c,t,m,'Prepare',target_id=RIGHT)
    turn(t,m,RIGHT)
    e,p=cast(c,t,m,'Cause',{'choice:needle.drunken_swaying_step':[]},target_id=LEFT)
    assert any('Swaying Guard' in str(v) for v in p)
    assert any(v.condition_id==IMAGE for v in e.state.actors[LEFT].conditions.values())==owned
    assert not e.state.actors[LEFT].reaction_available
    from tests.auto_worker1_support import settle
    result,p=settle(lambda answers:act(t,m,'Cause',answers,target_id=LEFT),choose=lambda prompt:[])
    assert result['status']=='COMMITTED'
    e=reload(c,m)
    roll=next(r for r in reversed(e.rolls) if r.actor_id==RIGHT and r.reason.startswith('ATTACK:'))
    assert roll.mode==('DISADVANTAGE' if owned else 'NORMAL')
    assert not any(v.condition_id==IMAGE for v in e.state.actors[LEFT].conditions.values())
    assert not any(v.event_type=='GM_RIDER' for v in e.events if 'Afterimage' in str(v.payload))


def test_unused_afterimage_expires_at_owner_turn_start(tmp_path):
    def pin(bundle):
        if bundle['actor_id']==RIGHT:
            for a in bundle['action_catalog']:
                a.get('parameters',{}).get('typed',{}).setdefault('numbers',{})['attack_bonus']=-100
    c,t,m=fight(tmp_path,[SWAY,AFTERIMAGE],prepare=[MARK],
        cause=[{'type':'attack','attack_kind':'cultivation_ranged','count':1,'no_damage':True}],bundle_edit=pin)
    cast(c,t,m,'Prepare',target_id=RIGHT)
    turn(t,m,RIGHT)
    e,p=cast(c,t,m,'Cause',{'choice:needle.drunken_swaying_step':[]},target_id=LEFT)
    assert any(v.condition_id==IMAGE for v in e.state.actors[LEFT].conditions.values())
    turn(t,m,LEFT)
    assert not any(v.condition_id==IMAGE for v in reload(c,m).state.actors[LEFT].conditions.values())

MOMENTUM='TAL_DRUNKEN_STYLE_BORROWED_MOMENTUM'

@pytest.mark.parametrize('marked,accept',[(True,True),(True,False),(False,True)])
def test_borrowed_momentum_asks_owner_for_supported_target_destination(tmp_path,marked,accept):
    c,t,m=fight(tmp_path,[BROKEN,MOMENTUM],prepare=[MARK] if marked else [],bundle_edit=_pin())
    if marked:cast(c,t,m,'Prepare',target_id=RIGHT)
    before=reload(c,m).state.actors
    picks={'choice:needle.drunken_borrowed_momentum_use':['use'] if accept else [],
           'choice:needle.drunken_borrowed_momentum':['cell:5,6']}
    e,p=cast(c,t,m,STRIKE,picks,target_id=RIGHT)
    moved=marked and accept
    assert (e.state.actors[RIGHT].position!=before[RIGHT].position)==moved
    assert e.state.actors[LEFT].position==before[LEFT].position
    if moved:assert e.state.actors[RIGHT].position.x==5
    assert e.state.actors[LEFT].movement_remaining_ft==before[LEFT].movement_remaining_ft
    assert not any(v.event_type=='GM_RIDER' for v in e.events)
    assert bool([v for v in p if v['context']['reaction_source_id']=='choice:needle.drunken_borrowed_momentum'])==moved


@pytest.mark.parametrize('talent',[BEAT,SLIP])
def test_rhythm_decline_does_not_spend_focus_or_roll_save(tmp_path,talent):
    c,t,m=setup(tmp_path,talent)
    before=reload(c,m).state.actors[LEFT].resources[FOCUS]
    e,p=cast(c,t,m,STRIKE,{USE_IDS[talent]:[]},target_id=RIGHT)
    assert any(v['context']['reaction_source_id']==USE_IDS[talent] for v in p)
    assert not [v for v in e.events if v.event_type=='SAVE_ROLLED']
    assert e.state.actors[LEFT].resources[FOCUS]==before


@pytest.mark.parametrize('talent',[BEAT,SLIP,MOMENTUM])
def test_ai_qualifying_hit_automatically_resolves_rhythm(tmp_path,talent):
    from tests.auto_worker1_support import action_sender
    c,t,m=fight(tmp_path,[BROKEN,talent],prepare=[MARK],bundle_edit=_pin(save_dc=100))
    cast(c,t,m,'Prepare',target_id=RIGHT)
    result,p=resolve(action_sender(c,t,m,STRIKE,ai=True,target_id=RIGHT))
    assert result['status']=='COMMITTED'
    e=reload(c,m)
    assert not any(v.event_type=='GM_RIDER' for v in e.events)
    if talent==BEAT:assert any(v.condition_id=='condition:typed.drunken_missing_beat' for v in e.state.actors[RIGHT].conditions.values())
    elif talent==SLIP:assert [v for v in e.events if v.event_type=='SAVE_ROLLED']
    else:assert e.state.actors[RIGHT].position.x!=4 or e.state.actors[RIGHT].position.y!=6


def test_missing_beat_without_focus_does_not_roll_or_offer_activation(tmp_path):
    spend={'type':'spend_resource','resource_id':FOCUS,'flat':1,'applies_to':'self'}
    c,t,m=fight(tmp_path,[BROKEN,BEAT],prepare=[MARK,spend],bundle_edit=_pin(save_dc=100))
    cast(c,t,m,'Prepare',target_id=RIGHT)
    e,p=cast(c,t,m,STRIKE,target_id=RIGHT)
    assert e.state.actors[LEFT].resources[FOCUS]==0
    assert not any(v.event_type=='SAVE_ROLLED' for v in e.events)
    assert not any('_use' in str(v['context']['reaction_source_id']) for v in p)


def test_borrowed_momentum_offers_owner_step_only_when_target_cannot_move(tmp_path):
    def block(arena):
        arena['terrain_regions'].append({'region_id':'test.momentum.ring','terrain_type':'BLOCKED',
            'movement_cost':1,'description':'Enclosed target',
            'cells':[{'x':x,'y':y} for x in range(3,6) for y in range(5,8) if (x,y) not in [(3,6),(4,6)]]})
    c,t,m=fight(tmp_path,[BROKEN,MOMENTUM],prepare=[MARK],bundle_edit=_pin(),arena_edit=block)
    cast(c,t,m,'Prepare',target_id=RIGHT)
    before=reload(c,m).state.actors
    e,p=cast(c,t,m,STRIKE,{'choice:needle.drunken_borrowed_step':['cell:2,6']},target_id=RIGHT)
    assert e.state.actors[RIGHT].position==before[RIGHT].position
    assert e.state.actors[LEFT].position.x==2
    assert any(v['context']['reaction_source_id']=='choice:needle.drunken_borrowed_step' for v in p)


def test_afterimage_range_gate_and_ineligible_next_attack_still_spends_it(tmp_path):
    def pin(bundle):
        if bundle['actor_id']==RIGHT:
            for a in bundle['action_catalog']:
                a.get('parameters',{}).get('typed',{}).setdefault('numbers',{})['attack_bonus']=-100
    c,t,m=fight(tmp_path,[SWAY,AFTERIMAGE],prepare=[MARK],
        cause=[{'type':'attack','attack_kind':'cultivation_ranged','count':1,'no_damage':True}],bundle_edit=pin)
    cast(c,t,m,'Prepare',target_id=RIGHT)
    turn(t,m,RIGHT)
    e,p=cast(c,t,m,'Cause',{'choice:needle.drunken_swaying_step':[]},target_id=LEFT)
    assert any(v.condition_id==IMAGE for v in e.state.actors[LEFT].conditions.values())
    state=t.state(m); menu=state['menu']
    from combat.gate2_runtime_models import Position
    move=next(o for o in menu['moves'] if o.get('destination') and e.grid.distance_ft(e.state.actors[LEFT].position,Position(**o['destination']))>30)
    assert t.act(m,move['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'],[])['status']=='COMMITTED'
    from tests.auto_worker1_support import settle
    result,p=settle(lambda answers:act(t,m,'Cause',answers,target_id=LEFT),choose=lambda prompt:[])
    assert result['status']=='COMMITTED'
    e=reload(c,m)
    assert e._distance_actor_to_actor(e.state.actors[LEFT],e.state.actors[RIGHT])>30
    roll=next(r for r in reversed(e.rolls) if r.actor_id==RIGHT and r.reason.startswith('ATTACK:'))
    assert roll.mode=='NORMAL'
    assert not any(v.condition_id==IMAGE for v in e.state.actors[LEFT].conditions.values())

@pytest.mark.parametrize('thrown',[False,True])
def test_borrowed_momentum_applies_to_ordinary_melee_but_not_thrown_attacks(tmp_path,thrown):
    from tests.test_auto104_drunken_rhythms import _pin_weapon
    c,t,m=fight(tmp_path,[MOMENTUM],prepare=[MARK],bundle_edit=_pin_weapon(hit=True))
    cast(c,t,m,'Prepare',target_id=RIGHT)
    label='Bi Shou (Dagger) thrown' if thrown else 'Bi Shou (Dagger) attack'
    e,p=cast(c,t,m,label,{'choice:needle.drunken_borrowed_momentum':['cell:5,6']},target_id=RIGHT)
    assert (e.state.actors[RIGHT].position.x==5)==(not thrown)
    assert bool([v for v in p if '_use' in str(v['context']['reaction_source_id'])])==(not thrown)

@pytest.mark.parametrize('decline',[BEAT,SLIP])
def test_two_owned_rhythms_keep_independent_player_consent(tmp_path,decline):
    c,t,m=fight(tmp_path,[BROKEN,BEAT,SLIP],prepare=[MARK],bundle_edit=_pin(save_dc=100))
    cast(c,t,m,'Prepare',target_id=RIGHT)
    e,p=cast(c,t,m,STRIKE,{USE_IDS[decline]:[],
                         'choice:needle.drunken_slipping_palm':['prone']},target_id=RIGHT)
    assert {v['context']['reaction_source_id'] for v in p if v['context']['reaction_source_id'] in USE_IDS.values()}==(set(USE_IDS.values()) if decline==BEAT else {USE_IDS[BEAT]})
    assert len([v for v in e.events if v.event_type=='SAVE_ROLLED'])==1
    assert e.state.actors[LEFT].resources[FOCUS]==(1 if decline==BEAT else 0)
    assert any(v.condition_id=='condition:typed.prone' for v in e.state.actors[RIGHT].conditions.values())==(decline==BEAT)
    assert any(v.condition_id=='condition:typed.drunken_missing_beat' for v in e.state.actors[RIGHT].conditions.values())==(decline==SLIP)

@pytest.mark.parametrize('owner_size,allowed',[('Tiny',False),('Small',True),('Medium',True)])
def test_slipping_prone_uses_size_categories_not_equal_one_cell_footprints(tmp_path,owner_size,allowed):
    def edit(bundle):
        _pin(save_dc=100)(bundle)
        if bundle['actor_id']==LEFT:bundle['actor_template']['size_category']=owner_size
    c,t,m=fight(tmp_path,[BROKEN,SLIP],prepare=[MARK],bundle_edit=edit)
    cast(c,t,m,'Prepare',target_id=RIGHT)
    e,p=cast(c,t,m,STRIKE,{'choice:needle.drunken_slipping_palm':['prone' if allowed else 'step'],
                         'choice:needle.drunken_slipping_step':[]},target_id=RIGHT)
    asked=next(v for v in p if v['context']['reaction_source_id']=='choice:needle.drunken_slipping_palm')
    assert ('prone' in {o['id'] for o in asked['choice']['options']})==allowed
    assert any(v.condition_id=='condition:typed.prone' for v in e.state.actors[RIGHT].conditions.values())==allowed

WRONG='TAL_DRUNKEN_STYLE_WRONG_HAND_STRIKE'

@pytest.mark.parametrize('item,choice,owned,ai,legacy',[
    ('fu','DEX',True,False,False),('fu','STR',True,False,False),
    ('fu','DEX',True,True,False),('fu','DEX',False,False,False),
    ('fu','DEX',True,False,True),('ji','DEX',True,False,False),
    ('chui','DEX',True,False,False),(None,'DEX',True,False,False),
    ('bi_shou','STR',True,False,False),
])
def test_wrong_hand_chooses_attack_and_damage_ability_without_rewriting_catalog(tmp_path,monkeypatch,item,choice,owned,ai,legacy):
    import copy
    import tests.auto_worker1_support as fixture
    original_sheet=fixture.sheet
    def distinct_scores(*args,**kwargs):
        doc=original_sheet(*args,**kwargs)
        for row in doc['ability_scores_and_statistics']['abilities']:
            if row['ability']=='DEX':row.update(score=18,modifier=4)
        return doc
    monkeypatch.setattr(fixture,'sheet',distinct_scores)
    def pin(bundle):
        _pin()(bundle)
        if legacy:
            for a in bundle['action_catalog']:
                a.get('parameters',{}).get('typed',{}).pop('drunken_wrong_hand',None)
    names={'fu':'Fu (Short Axe)','ji':'Ji (Halberd)','chui':'Chui (Hammer)','bi_shou':'Bi Shou (Dagger)'}
    kit={'items':[] if item is None else [{'item_id':'tianxia.mortal.weapon.'+item,'name':names[item],'quantity':1}]}
    c,t,m=fight(tmp_path,[BROKEN,*([WRONG] if owned else [])],left_kit=kit,bundle_edit=pin)
    e=reload(c,m)
    label=next(g['label'] for g in t.state(m)['menu']['actions'] if g['label'].startswith('Broken-Rhythm Strike:')
               and (names[item] in g['label'] if item else 'Unarmed' in g['label']))
    action=next(a for a in e.action_catalog.values() if a.owner_id==LEFT and a.display_name==label)
    before=copy.deepcopy(action.parameters)
    old_mod=before['typed'].get('drunken_wrong_hand',{}).get('original_mod',before['typed']['weapon'].get('ability_modifier',2))
    old_damage=before['typed']['weapon']['damage']['modifier']
    enabled=owned and not legacy and item!='ji'
    selected='DEX' if ai else choice
    selected_mod=4 if selected=='DEX' else 2
    delta=selected_mod-old_mod if enabled else 0
    if ai:
        from tests.auto_worker1_support import action_sender
        result,p=resolve(action_sender(c,t,m,label,ai=True,target_id=RIGHT))
        assert result['status']=='COMMITTED'
        e=reload(c,m)
    else:
        e,p=cast(c,t,m,label,{'choice:needle.drunken_wrong_hand':[choice]},target_id=RIGHT)
    attack=next(r for r in reversed(e.rolls) if r.actor_id==LEFT and r.reason.startswith('ATTACK:'))
    damage=next(r for r in reversed(e.rolls) if r.actor_id==LEFT and r.reason.startswith('DAMAGE:'))
    assert attack.modifier==100+delta
    if 'fixed_damage' in before['typed']['weapon']:
        assert damage.modifier==old_damage
        assert damage.total==max(0,1+selected_mod) if enabled else damage.total==before['typed']['weapon']['fixed_damage']
    else:
        assert damage.modifier==old_damage+delta
    assert e.action_catalog[action.source_definition_id].parameters==before
    assert not any(v.event_type=='GM_RIDER' for v in e.events)
    if not ai:
        asked=[v for v in p if v['context']['reaction_source_id']=='choice:needle.drunken_wrong_hand']
        assert bool(asked)==enabled
        if enabled:assert {o['id'] for o in asked[0]['choice']['options']}=={'STR','DEX'}


def test_one_new_rhythm_per_hit_even_when_both_are_accepted(tmp_path):
    c,t,m=fight(tmp_path,[BROKEN,BEAT,SLIP],prepare=[MARK],bundle_edit=_pin(save_dc=100))
    cast(c,t,m,'Prepare',target_id=RIGHT)
    e,p=cast(c,t,m,STRIKE,target_id=RIGHT)
    assert len([v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT])==1
    uses=[v for v in p if v['context']['reaction_source_id'] in USE_IDS.values()]
    assert len(uses)==1


@pytest.mark.parametrize('ability',['STR','DEX'])
def test_wrong_hand_and_hit_riders_share_the_style_talent_limit(tmp_path,ability):
    kit={'items':[{'item_id':'tianxia.mortal.weapon.fu','name':'Fu (Short Axe)','quantity':1}]}
    c,t,m=fight(tmp_path,[BROKEN,WRONG,BEAT],left_kit=kit,prepare=[MARK],bundle_edit=_pin(save_dc=100))
    cast(c,t,m,'Prepare',target_id=RIGHT)
    e,p=cast(c,t,m,'Broken-Rhythm Strike: Fu (Short Axe)',{'choice:needle.drunken_wrong_hand':[ability]},target_id=RIGHT)
    assert len([v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT])==(1 if ability=='STR' else 0)
    assert e.state.actors[LEFT].resources[FOCUS]==(0 if ability=='STR' else 1)
