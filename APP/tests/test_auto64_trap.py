"""Warning and shield decisions resolve through committed trap placements."""
import pytest
from combat.ext import placed
from tests.cw2_service_support import seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_carry import KIT


def save_failure(bundles):
    bundles[1]['actor_template']['saving_throws']['DEX']=-100
    seal(bundles[1])


def set_warning(combat, table, mid, selected):
    settle(table,mid,candidate(combat,mid,'Trap form: Tripwire').candidate_id)
    settle(table,mid,candidate(combat,mid,'Trap trigger: Warning Trigger').candidate_id)
    return settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,7)).candidate_id,
                  {'choice:needle.trap_warn':selected})


def enter_trap(combat,table,mid,accept=None):
    turn(table,mid,ALLY)
    e=combat._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination
              and (c.destination.x,c.destination.y,c.destination.z)==(4,7,0))
    return settle(table,mid,move.candidate_id,{'choice:needle.trap_warned_trigger':'use' if accept else None})


def test_warning_can_warn_a_hostile_and_leave_an_ally_unwarned(tmp_path):
    combat,table,mid=fixture(tmp_path,['TAL_TRAP_WARNING_TRIGGER'],bundle_transform=save_failure)
    prompts=set_warning(combat,table,mid,[FOE])
    p=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.trap_warn')
    assert {o['id'] for o in p['choice']['options']} == {OWNER,ALLY,FOE}
    e=reload(tmp_path,mid)
    zone=placed.of(e,'trap')[0]
    assert placed.data(zone)['warned']==[FOE]
    enter_trap(combat,table,mid)
    assert any(c.condition_id=='condition:typed.prone' for c in reload(tmp_path,mid).state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('accept',[True,False])
def test_later_warning_and_warned_creature_may_choose_to_trigger(tmp_path,accept):
    combat,table,mid=fixture(tmp_path,['TAL_TRAP_WARNING_TRIGGER'],bundle_transform=save_failure)
    set_warning(combat,table,mid,None)
    prompts=settle(table,mid,candidate(combat,mid,'Warn creatures about a trap',at=(4,7)).candidate_id,
        {'choice:needle.trap_warn_later':[ALLY]})
    assert any(p['context']['reaction_source_id']=='choice:needle.trap_warn_later' for p in prompts)
    e=reload(tmp_path,mid)
    assert placed.data(placed.of(e,'trap')[0])['warned']==[ALLY]
    prompts=enter_trap(combat,table,mid,accept)
    assert any(p['context']['reactor_id']==ALLY and p['context']['reaction_source_id']=='choice:needle.trap_warned_trigger' for p in prompts)
    e=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.prone' for c in e.state.actors[ALLY].conditions.values()) == accept
    assert placed.data(placed.of(e,'trap')[0])['warned']==[ALLY]


@pytest.mark.parametrize('shield,accept',[(True,True),(True,False),(False,False)])
def test_trapped_shield_requires_a_real_shield_and_owner_reaction_consent(tmp_path,shield,accept):
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.armor.shield','name':'Shield','quantity':1}]}} if shield else None
    combat,table,mid=fixture(tmp_path,['TAL_TRAP_TRAPPED_SHIELD'],owner_kit=kit,owner_ac=100,
        foe_position={'x':3,'y':5},foe_kit={'starting_kit':{'items':[KIT['items'][-1]]}})
    settle(table,mid,candidate(combat,mid,'Trap deployment: Trapped Shield').candidate_id)
    e=reload(tmp_path,mid)
    sets=[c for c in e.legal_candidates() if c.source_definition_id in e.action_catalog and e.action_catalog[c.source_definition_id].display_name=='Set Trap']
    assert bool(sets)==shield
    if not shield:return
    settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,7)).candidate_id)
    trap_source=placed.of(reload(tmp_path,mid),'trap')[0].source_definition_id
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Bi Shou (Dagger) attack',target=OWNER).candidate_id,
        {'choice:needle.trapped_shield':'use' if accept else None})
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.trapped_shield' for p in prompts)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].reaction_available != accept
    assert bool(placed.of(e,'trap')) != accept
    shots=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==OWNER and v.source_definition_id==trap_source and FOE in v.target_ids]
    assert bool(shots)==accept


def test_trapped_shield_does_not_spring_for_a_ranged_miss(tmp_path):
    """The printed trigger is "A creature misses you with a melee attack while you wield the shield" -- a ranged miss is
    not a trigger. The reaction hook reads the attack's range; this proves a missed shot leaves the Reaction and the
    attached Dart Mechanism alone. Regression for review finding 1 (only the melee-miss path was exercised)."""
    from tests.worker2_support import sealed_native_attack
    def bow(bundles):
        sealed_native_attack(bundles[2],'Test bow shot',damage_type='PIERCING',count=1,sides=4,modifier=0,
            attack_bonus=-100,range_ft=60)
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.armor.shield','name':'Shield','quantity':1}]}}
    combat,table,mid=fixture(tmp_path,['TAL_TRAP_TRAPPED_SHIELD'],owner_kit=kit,owner_ac=100,
        foe_position={'x':3,'y':5},bundle_transform=bow)
    settle(table,mid,candidate(combat,mid,'Trap deployment: Trapped Shield').candidate_id)
    settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,7)).candidate_id)
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Test bow shot',target=OWNER).candidate_id)
    assert not any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.trapped_shield' for p in prompts)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].reaction_available  # nothing was spent
    assert not [v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==OWNER]  # the dart did not fire
    assert placed.of(e,'trap')


def test_existing_route_preparation_chooses_legal_spaces_and_reloads(tmp_path):
    from tests.test_hunt35_trap_setup import test_prepared_traps_choose_or_decline_before_first_turn_and_reload, ROUTE
    test_prepared_traps_choose_or_decline_before_first_turn_and_reload(tmp_path,ROUTE,False,False)


def test_trapped_shield_springs_for_a_held_shield_whose_shield_bonus_is_zero(tmp_path, monkeypatch):
    """Wielding is the printed condition, not the Shield Bonus: an unbroken shield in hand that earns no Shield Bonus this fight
    still springs the trap. The gate read the earned bonus before the wielding helper; with the bonus at 0 it would not fire."""
    from combat import armour
    monkeypatch.setattr(armour, 'shield_bonus_earning', lambda engine, actor: 0)
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.armor.shield','name':'Shield','quantity':1}]}}
    combat,table,mid=fixture(tmp_path,['TAL_TRAP_TRAPPED_SHIELD'],owner_kit=kit,owner_ac=100,
        foe_position={'x':3,'y':5},foe_kit={'starting_kit':{'items':[KIT['items'][-1]]}})
    settle(table,mid,candidate(combat,mid,'Trap deployment: Trapped Shield').candidate_id)
    settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,7)).candidate_id)
    trap_source=placed.of(reload(tmp_path,mid),'trap')[0].source_definition_id
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Bi Shou (Dagger) attack',target=OWNER).candidate_id,
        {'choice:needle.trapped_shield':'use'})
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.trapped_shield' for p in prompts)
    e=reload(tmp_path,mid)
    assert not e.state.actors[OWNER].reaction_available
    shots=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==OWNER and v.source_definition_id==trap_source and FOE in v.target_ids]
    assert shots
