"""New Jester packets: actual next-roll consumption and owner ally/action choices."""
import pytest
from combat.gate2_runtime_models import ActionDefinition
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_carry import KIT

T='tianxia.talent.jester.'
NATIVE='action:test.cw2.jester.native'

def setup(bundles):
    for b,bonus in zip(bundles,[100,-100,0]):
        b['actor_template']['initiative_bonus']=bonus
        seal(b)
    bundles[2]['actor_template']['saving_throws']['WIS']=-100
    add_action(bundles[2],'Foil technique',[],target='SELF')
    add_action(bundles[2],'Actual skill check',[{'type':'skill_check','ability':'DEX','skill':'Acrobatics'}])
    add_action(bundles[2],'Check Advantage',[{'type':'condition','condition':'check_mode','applies_to':'self',
        'expires_on':'UNTIL_REMOVED','condition_data':{'rule':{'check_mode':{'ALL':'ADVANTAGE'}}}}],target='SELF')
    for b,actor in [(bundles[1],ALLY),(bundles[2],FOE)]:
        a=ActionDefinition(source_definition_id=NATIVE+actor,display_name='Native free attack',owner_id=actor,
            economy='NONE',resolution_kind='ATTACK',target_kind='ANY_CREATURE',range_ft=120,
            attack_bonus=6,damage={'count':1,'sides':4,'modifier':0},damage_type='BLUDGEONING')
        b['action_catalog'].append(a.model_dump(mode='json'));b['actor_template']['action_ids'].append(a.source_definition_id);seal(b)

def flustered_fixture(tmp_path):
    combat,table,mid=fixture(tmp_path,[T+'a_fine_display'],owner_ac=100,foe_position={'x':3,'y':5},
        foe_kit={'starting_kit':{'items':[KIT['items'][-1]]}},bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Set the Scene: Strike the Fool',target=FOE).candidate_id)
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Bi Shou (Dagger) attack',target=OWNER).candidate_id,
        {'choice:needle.strike_the_fool':'fine_display'})
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.strike_the_fool' for p in prompts)
    assert any(c.condition_id=='condition:typed.flustered' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
    return combat,table,mid

@pytest.mark.parametrize('advantage',[False,True])
def test_flustered_next_check_consumes_penalty_even_when_modes_cancel(tmp_path,advantage):
    combat,table,mid=flustered_fixture(tmp_path)
    if advantage:settle(table,mid,candidate(combat,mid,'Check Advantage',target=FOE).candidate_id)
    settle(table,mid,candidate(combat,mid,'Actual skill check',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    checks=[r for r in e.rolls if r.reason.startswith('CHECK:action:test.cw2.') and 'Acrobatics' in r.reason]
    assert checks[-1].mode==('NORMAL' if advantage else 'DISADVANTAGE')
    c=next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.flustered')
    assert c.data['disadvantage'] is False and not e.state.actors[FOE].reaction_available
    settle(table,mid,candidate(combat,mid,'Actual skill check',target=FOE).candidate_id)
    assert [r for r in reload(tmp_path,mid).rolls if 'Acrobatics' in r.reason][-1].mode==('ADVANTAGE' if advantage else 'NORMAL')
    turn(table,mid,OWNER)
    assert not any(c.condition_id=='condition:typed.flustered' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())

def test_flustered_native_attack_consumes_the_same_next_roll(tmp_path):
    combat,table,mid=flustered_fixture(tmp_path)
    for expected in ['DISADVANTAGE','NORMAL']:
        settle(table,mid,candidate(combat,mid,'Native free attack',target=ALLY).candidate_id)
        e=reload(tmp_path,mid)
        assert [r for r in e.rolls if r.reason.startswith('ATTACK:'+NATIVE)][-1].mode==expected
    assert not e.state.actors[FOE].reaction_available

@pytest.mark.parametrize('cancel',[False,True])
def test_flustered_typed_attack_consumes_only_after_a_roll(tmp_path,cancel):
    def configure(bundles):
        setup(bundles)
        bundles[1]['typed_reactions'].append({'block':'generic','kind':'attacked',
            'feature_id':'test:jester.cancel','name':'Cancel the declared attack',
            'effects':[{'type':'negate_attack','chance_d20':1}], 'costs':[], 'ask':True})
        seal(bundles[1])
        add_action(bundles[0],'Grant Flustered',[{'type':'flustered'}])
        add_action(bundles[2],'Typed free attack',[{'type':'attack','damage':{'count':1,'sides':4},
            'damage_type':'BLUDGEONING'}])
    combat,table,mid=fixture(tmp_path,[T+'a_fine_display'],bundle_transform=configure)
    # Both the grant and cancellation run through real table transactions.
    settle(table,mid,candidate(combat,mid,'Grant Flustered',target=FOE).candidate_id)
    turn(table,mid,FOE)
    before=len(reload(tmp_path,mid).rolls)
    settle(table,mid,candidate(combat,mid,'Typed free attack',target=ALLY).candidate_id,
        {'reaction:typed.test:jester.cancel':'first'} if cancel else {})
    e=reload(tmp_path,mid)
    attacks=[r for r in e.rolls[before:] if r.reason.startswith('ATTACK:') and r.actor_id==FOE]
    assert len(attacks)==(0 if cancel else 1)
    if attacks: assert attacks[0].mode=='DISADVANTAGE'
    c=next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.flustered')
    assert c.data['disadvantage'] is cancel
    settle(table,mid,candidate(combat,mid,'Actual skill check',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    assert [r for r in e.rolls if 'Acrobatics' in r.reason][-1].mode==('DISADVANTAGE' if cancel else 'NORMAL')
    settle(table,mid,candidate(combat,mid,'Actual skill check',target=FOE).candidate_id)
    assert [r for r in reload(tmp_path,mid).rolls if 'Acrobatics' in r.reason][-1].mode=='NORMAL'

def test_absurd_agreement_overlapping_grants_are_consumed_independently(tmp_path):
    def configure(bundles):
        setup(bundles)
        add_action(bundles[0],'Grant Absurd Agreement',[{'type':'jester_ally_advantage'}])
    combat,table,mid=fixture(tmp_path,[T+'absurd_agreement'],bundle_transform=configure)
    for foil in (FOE,OWNER):
        settle(table,mid,candidate(combat,mid,'Grant Absurd Agreement',target=foil).candidate_id,
            {'choice:needle.absurd_ally':ALLY})
    assert len([c for c in reload(tmp_path,mid).state.actors[ALLY].conditions.values()
        if c.condition_id.startswith('condition:typed.absurd_advantage.')])==2
    turn(table,mid,ALLY)
    for foil,expected in ((FOE,'ADVANTAGE'),(FOE,'NORMAL'),(OWNER,'ADVANTAGE'),(OWNER,'NORMAL')):
        settle(table,mid,candidate(combat,mid,'Native free attack',target=foil).candidate_id)
        e=reload(tmp_path,mid)
        assert [r for r in e.rolls if r.reason.startswith('ATTACK:'+NATIVE)][-1].mode==expected
        remaining=[c for c in e.state.actors[ALLY].conditions.values()
            if c.condition_id.startswith('condition:typed.absurd_advantage.')]
        assert len(remaining)==(1 if foil==FOE else 0)
        assert len([m for m in e.state.actors[ALLY].modifiers.values() if m.target_field=='attack_mode_vs'])==len(remaining)

@pytest.mark.parametrize('choice',['dash','disengage','dodge'])
def test_borrowed_action_asks_the_off_turn_owner_and_performs_ordinary_action(tmp_path,choice):
    combat,table,mid=fixture(tmp_path,[T+'borrowed_action_honest_consequence'],bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Set the Scene: Show Your Hand',target=FOE).candidate_id)
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[OWNER].movement_remaining_ft
    rid='reaction:typed.'+T+'borrowed_action_honest_consequence'
    prompts=settle(table,mid,candidate(combat,mid,'Foil technique',target=FOE).candidate_id,
        {rid:'first','choice:needle.borrowed_action':choice})
    p=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.borrowed_action')
    assert p['context']['reactor_id']==OWNER and 'hide' not in [o['id'] for o in p['choice']['options']]
    e=reload(tmp_path,mid);a=e.state.actors[OWNER]
    assert not a.reaction_available and a.action_available
    assert a.movement_remaining_ft==before+(30 if choice=='dash' else 0)
    assert bool(a.turn_flags.get('disengaged'))==(choice=='disengage')
    assert any(c.condition_id=='condition:core.dodge' for c in a.conditions.values())==(choice=='dodge')

@pytest.mark.parametrize('expire',[False,True])
def test_absurd_agreement_selected_ally_next_attack_vs_foil_and_expiry(tmp_path,expire):
    combat,table,mid=fixture(tmp_path,[T+'absurd_agreement'],bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Choose Absurd Agreement: One ally who saw the technique gains Advantage on its next attack roll against the Foil').candidate_id)
    settle(table,mid,candidate(combat,mid,'Set the Scene: Show Your Hand',target=FOE).candidate_id)
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Foil technique',target=FOE).candidate_id,
        {'reaction:typed.'+T+'absurd_agreement':'first','choice:needle.absurd_ally':ALLY})
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.absurd_ally' for p in prompts)
    turn(table,mid,ALLY)
    if expire:
        turn(table,mid,OWNER);turn(table,mid,ALLY)
    else:
        settle(table,mid,candidate(combat,mid,'Native free attack',target=OWNER).candidate_id)
        assert any(m.target_field=='attack_mode_vs' for m in reload(tmp_path,mid).state.actors[ALLY].modifiers.values())
    settle(table,mid,candidate(combat,mid,'Native free attack',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    assert [r for r in e.rolls if r.reason.startswith('ATTACK:'+NATIVE)][-1].mode==('NORMAL' if expire else 'ADVANTAGE')
    assert not any(c.condition_id.startswith('condition:typed.absurd_advantage.') for c in e.state.actors[ALLY].conditions.values())
    settle(table,mid,candidate(combat,mid,'Native free attack',target=FOE).candidate_id)
    assert [r for r in reload(tmp_path,mid).rolls if r.reason.startswith('ATTACK:'+NATIVE)][-1].mode=='NORMAL'
