"""Kind-filtered zones exercise actual compiled activations and recorded HP receipts."""
import pytest
from combat import zones, typed_executor
from combat.gate2_runtime_models import Position
from tests import lock8_support as S
from tests.test_lock8_radiance import kind_bundle
from tests.test_lock8_radiance_remaining import P, fixed
from combat.ext import radiance_states as R


def fight(feature, kind='Undead', ally=False):
    return S.fight(S.bundle(P+feature,cl=20,dc=16),
        foe=kind_bundle(['SAND_BASE_SCOURING_HAND'],S.FOE,kind,cl=20),
        ally=S.bundle('SAND_BASE_SCOURING_HAND',actor_id=S.ALLY) if ally else None)


@pytest.mark.parametrize('kind,affected',[('Undead',True),(None,False)])
def test_consecrated_boundary_terrain_save_and_one_trigger_per_turn(monkeypatch,kind,affected):
    e=fight('consecrated_boundary',kind);a,b=e.state.actors[S.ME],e.state.actors[S.FOE]
    fixed(monkeypatch,1)
    S.use(e,'Consecrated Boundary',at=(6,6))
    assert ((b.position.x,b.position.y) in zones.difficult_cells(e,b))==affected
    before=b.current_hp
    zones.on_turn_start(e,b)
    saves=S.payloads(e.events,'SAVE_ROLLED')
    assert bool(saves)==affected
    if affected:
        action=e.action_catalog[S.action_id(e,S.ME,'Consecrated Boundary')]
        numbers=action.parameters['typed']['numbers']
        assert before-b.current_hp==numbers['pb']+numbers['key_mod']
        assert bool(S.held(b,'reaction_denied'))
        zones.on_turn_start(e,b)
        assert before-b.current_hp==numbers['pb']+numbers['key_mod']
    else: assert before==b.current_hp


@pytest.mark.parametrize('feature,name,temp',[
    ('court_of_unshadowed_dawn','Court of Unshadowed Dawn',False),
    ('world_of_revealed_morning','World of Revealed Morning',True)])
@pytest.mark.parametrize('kind,denied',[('Demon',True),(None,False)])
def test_unclean_domain_denial_and_exit_expiry(feature,name,temp,kind,denied):
    e=fight(feature,kind);a,b=e.state.actors[S.ME],e.state.actors[S.FOE]
    S.use(e,name,at=(6,6) if temp else None)
    b.current_hp-=20;before=b.current_hp
    # Native healers write HP then append their receipt; restriction must also
    # cover this path, not only typed_executor.block_healing.
    b.current_hp+=10
    e._append_event('HEALING_APPLIED','test:heal',actor_id=S.FOE,target_ids=(S.FOE,),
                    payload={'offered':10,'before':before,'after':b.current_hp})
    assert b.current_hp==before+(0 if denied else 10)
    assert S.payloads(e.events,'HEALING_APPLIED')[-1]['after']==b.current_hp
    e._grant_temp_hp(b,8,'test:ward',S.FOE)
    assert b.temporary_hp==(0 if denied and temp else 8)
    e._end_concentration(a,'TEST')
    b.current_hp=before
    b.current_hp+=10
    e._append_event('HEALING_APPLIED','test:heal',actor_id=S.FOE,target_ids=(S.FOE,),
                    payload={'offered':10,'before':before,'after':b.current_hp})
    assert b.current_hp==before+10


def test_merciful_halo_replaces_only_its_casters_old_target():
    e=fight('halo_of_the_merciful_sovereign',ally=True);a,b=e.state.actors[S.ME],e.state.actors[S.ALLY]
    S.use(e,'Halo of the Merciful Sovereign',target=S.ME)
    a.bonus_action_available=True
    S.use(e,'Halo of the Merciful Sovereign',target=S.ALLY)
    assert not R.states(a,'merciful_halo') and R.states(b,'merciful_halo')
    assert not any(m.target_field=='damage_resistance' and m.value=='NECROTIC' for m in a.modifiers.values())
    assert any(m.target_field=='damage_resistance' and m.value=='NECROTIC' for m in b.modifiers.values())


@pytest.mark.parametrize('kind,mode',[('Undead','DISADVANTAGE'),(None,'NORMAL')])
def test_solar_radiance_strike_save_uses_target_kind(monkeypatch,kind,mode):
    e=fight('solar_radiance_form',kind);a,b=e.state.actors[S.ME],e.state.actors[S.FOE]
    fixed(monkeypatch,10);b.armor_class=0
    S.use(e,'Solar Radiance Form')
    a.action_available=True
    S.use(e,'Radiance Strike',target=S.FOE)
    saves=S.payloads(e.events,'SAVE_ROLLED')
    assert saves and saves[-1]['mode']==mode


@pytest.mark.parametrize('kind,denied',[('Undead',True),(None,False)])
def test_crown_failed_radiance_save_requires_unclean(monkeypatch,kind,denied):
    e=fight('crown_of_the_unblinking_sun',kind);b=e.state.actors[S.FOE]
    S.use(e,'Crown of the Unblinking Sun')
    fixed(monkeypatch,1)
    ctx=S.ctx_of(e,S.ME,S.FOE,S.action_id(e,S.ME,'Radiance Strike'))
    ctx.typed={**ctx.typed,'source':P+'test_save'}
    typed_executor.block_save(ctx,{'type':'save','ability':'wis','applies_to':'target','on_fail':[]})
    assert (bool(S.held(b,'reaction_denied')))==denied
