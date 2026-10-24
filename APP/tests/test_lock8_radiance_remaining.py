"""Remaining kind-aware Radiance consumers use real compiled abilities."""
import pytest
from combat import typed_executor, typed_reactions
from combat.ext import radiance_states as R
from combat.ext.radiance_unclean import SCRIPTURE, WARD
from tests import lock8_support as S
from tests.test_lock8_radiance import kind_bundle, mech
from tests.test_lock_choices import install

P='tianxia.talent.radiance.'


def fight(*features, kind='Undead', close=False):
    return S.fight(S.bundle(*features,cl=20,dc=16),
        foe=kind_bundle(['SAND_BASE_SCOURING_HAND'],S.FOE,kind,cl=20),foe_at=(4,6) if close else (6,6))


def fixed(monkeypatch, natural=10):
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':natural})


@pytest.mark.parametrize('kind,mode',[('Undead','DISADVANTAGE'),(None,'NORMAL')])
def test_daybreak_canonical_save_kind(kind,mode):
    e=fight(P+'daybreak_seal',kind=kind);a,b=e.state.actors[S.ME],e.state.actors[S.FOE]
    ctx=S.ctx_of(e,S.ME,S.FOE,S.action_id(e,S.ME,'Radiance Strike'))
    typed_executor.block_mark(ctx,{'mark':'Dawnmark','applies_to':'target'})
    typed_executor.run_effects(ctx,mech(P+'daybreak_seal')['modifier']['effects'])
    saves=S.payloads(e.events,'SAVE_ROLLED');assert saves[-1]['mode']==mode


@pytest.mark.parametrize('kind,extra',[('Fiend',True),(None,False)])
def test_scripture_actual_damage_once_per_turn_and_no_recursion(kind,extra):
    e=fight(SCRIPTURE,kind=kind);a,b=e.state.actors[S.ME],e.state.actors[S.FOE]
    ctx=S.ctx_of(e,S.ME,S.FOE,S.action_id(e,S.ME,'Radiance Strike'))
    typed_executor.block_mark(ctx,{'mark':'Dawnmark','applies_to':'target'})
    before=b.current_hp
    e._commit_damage(b,1,'FIRE','test:hit',S.ME,None,reaction_depth=0)
    bonus=[ev for ev in e.events if ev.source_definition_id==SCRIPTURE and ev.event_type=='DAMAGE_ROLLED']
    assert bool(bonus)==extra
    assert before-b.current_hp==1+(bonus[0].payload['total'] if extra else 0)
    e._commit_damage(b,1,'FIRE','test:hit',S.ME,None,reaction_depth=0)
    assert len([ev for ev in e.events if ev.source_definition_id==SCRIPTURE and ev.event_type=='DAMAGE_ROLLED'])==int(extra)


@pytest.mark.parametrize('kind,bonus',[('Demon',True),(None,False)])
def test_dawn_ward_reaction_reduction_uses_actual_attacker_kind(monkeypatch,kind,bonus):
    e=fight(WARD,kind=kind);a,b=e.state.actors[S.ME],e.state.actors[S.FOE]
    row={'feature_id':WARD,'effects':[{'type':'damage_modifier','flat':3}], 'numbers':{'pb':a.proficiency_bonus,'cl':20}}
    remaining,_=typed_reactions._generic_damage_reduction(e,a,row,30,protected=a,attacker=b)
    assert remaining==27-(a.proficiency_bonus if bonus else 0)


@pytest.mark.parametrize('name,tag',[('Searing Halo','searing_halo'),('Solar Radiance Form','solar_form'),
                                  ('Crown of the Unblinking Sun','crown')])
def test_timed_buffs_cost_concentration_and_expiry(name,tag):
    feature={'searing_halo':'searing_halo','solar_form':'solar_radiance_form','crown':'crown_of_the_unblinking_sun'}[tag]
    e=fight(P+feature);a=e.state.actors[S.ME];before=a.resources['resource:core.qi']
    S.use(e,name)
    assert R.states(a,tag) and a.concentration is not None
    assert before-a.resources['resource:core.qi']=={'searing_halo':2,'solar_form':8,'crown':10}[tag]
    e._end_concentration(a,'TEST')
    assert not R.states(a,tag)


def test_searing_hit_retaliation_survives_concentration_loss(monkeypatch):
    e=fight(P+'searing_halo',close=True);a,b=e.state.actors[S.ME],e.state.actors[S.FOE]
    S.use(e,'Searing Halo');before=b.current_hp
    fixed(monkeypatch,20)
    from combat import ext
    def lose(engine,event_type,kwargs):
        if event_type=='DAMAGE_COMMITTED' and S.ME in kwargs.get('target_ids',()):
            engine._end_concentration(a,'TEST_HIT')
    ext.effects();monkeypatch.setitem(ext._HOOKS,'event',[*ext._HOOKS.get('event',[]),lose])
    from combat.gate2_runtime_models import DiceSpec
    e._resolve_attack_spec(b,a,{'attack_bonus':100,'reach_ft':5,'damage':DiceSpec(count=1,sides=2,modifier=0),'fixed_damage':1},None,
                           source_definition_id='test:melee')
    assert not R.states(a,'searing_halo')
    assert before-b.current_hp==a.proficiency_bonus


@pytest.mark.parametrize('kind,mode',[('Undead','ADVANTAGE'),(None,'NORMAL')])
def test_searing_fear_save_requires_unclean_source(kind,mode):
    e=fight(P+'searing_halo',kind=kind);S.use(e,'Searing Halo')
    ctx=S.ctx_of(e,S.FOE,S.ME,S.action_id(e,S.FOE,'Scouring Hand'))
    typed_executor.block_save(ctx,{'type':'save','ability':'wis','applies_to':'target',
        'on_fail':[{'type':'condition','condition':'frightened','applies_to':'target'}]})
    assert S.payloads(e.events,'SAVE_ROLLED')[-1]['mode']==mode


@pytest.mark.parametrize('kind,reduced',[('Undead',True),(None,False)])
def test_merciful_halo_only_reduces_unclean_source_and_replaces_old_target(kind,reduced):
    e=fight(P+'halo_of_the_merciful_sovereign',kind=kind);a,b=e.state.actors[S.ME],e.state.actors[S.FOE]
    S.use(e,'Halo of the Merciful Sovereign',target=S.ME)
    assert R.states(a,'merciful_halo') and a.concentration is None
    before=a.current_hp
    e._commit_damage(a,10,'FIRE','test:fire',S.FOE,None,reaction_depth=0)
    assert before-a.current_hp==10-(a.proficiency_bonus if reduced else 0)


@pytest.mark.parametrize('kind,allowed',[('Undead',True),(None,False)])
def test_burning_purification_kind_range_cost_and_persistent_attack_penalty(monkeypatch,kind,allowed):
    e=fight(P+'purifying_radiance',kind=kind,close=True);a,b=e.state.actors[S.ME],e.state.actors[S.FOE]
    assert ('Burning Purification' in S.legal(e))==allowed
    if not allowed:return
    fixed(monkeypatch,10);b.armor_class=0
    before=a.resources['resource:core.qi'];S.use(e,'Burning Purification',target=S.FOE)
    assert a.resources['resource:core.qi']==before-3
    assert e._attack_mode(b,a)=='DISADVANTAGE'
    e._consume_attack_modifiers(b)
    assert e._attack_mode(b,a)=='DISADVANTAGE'
    e._expire_for_checkpoint('START_OF_TURN',S.ME)
    assert e._attack_mode(b,a)=='NORMAL'
