"""Dodge only penalizes attacks the defender can see, through the shared knowledge seam."""
import pytest
from combat import senses, target_knowledge
from combat.gate5_service import CombatService
from tests.h1_support import duel, ME, FOE, ROOT
from tests.test_tabletop_hunt6 import table_fight, LEFT, RIGHT, ALLY
from tests.test_lock2_persistence import act
from tests.test_hidden_targeting import turn
from tests.r10_fixup_support import cast_sender, commit


def condition(e,actor,name):
    e._apply_condition(actor,name,'test:condition',actor.entity_id,expires_on='UNTIL_REMOVED')


@pytest.mark.parametrize('invisible,dodge,mode',[(False,False,'NORMAL'),(False,True,'DISADVANTAGE'),
                                             (True,False,'ADVANTAGE'),(True,True,'ADVANTAGE')])
def test_native_dodge_requires_defender_sight(invisible,dodge,mode):
    e=duel([]);attacker,defender=e.state.actors[ME],e.state.actors[FOE]
    if invisible:condition(e,attacker,'condition:typed.invisible')
    if dodge:condition(e,defender,'condition:core.dodge')
    assert e._attack_mode(attacker,defender)==mode


def test_pinpointing_without_sight_does_not_restore_dodge(monkeypatch):
    e=duel([]);attacker,defender=e.state.actors[ME],e.state.actors[FOE]
    condition(e,attacker,'condition:typed.invisible')
    condition(e,defender,'condition:core.dodge')
    monkeypatch.setattr(senses,'pinpoints',lambda *a:True)
    assert target_knowledge.located(e,defender,attacker)
    assert not target_knowledge.can_see(e,defender,attacker)
    assert e._attack_mode(attacker,defender)=='ADVANTAGE'


def test_sight_override_restores_dodge_through_shared_seam(monkeypatch):
    e=duel([]);attacker,defender=e.state.actors[ME],e.state.actors[FOE]
    condition(e,attacker,'condition:typed.invisible')
    condition(e,defender,'condition:core.dodge')
    e._apply_condition(defender, senses.SENSE, 'test:blindsight', defender.entity_id,
                       expires_on='UNTIL_REMOVED', data={'sense': 'blindsight', 'range_ft': 30})
    assert target_knowledge.can_see(e,defender,attacker)
    # The existing special-sense mask removes Invisible's Advantage before the
    # native query, leaving Dodge's Disadvantage against the now-seen attacker.
    assert e._attack_mode(attacker,defender)=='DISADVANTAGE'


def test_blinded_defender_cannot_dodge_the_attack_but_keeps_dex_save_rule():
    e=duel([]);attacker,defender=e.state.actors[ME],e.state.actors[FOE]
    condition(e,defender,'condition:core.dodge')
    condition(e,defender,'condition:typed.blinded')
    assert not target_knowledge.can_see(e,defender,attacker)
    assert e._attack_mode(attacker,defender)=='ADVANTAGE'
    roll=e._roll_save(defender,'DEX',15,'test:save')
    assert roll.mode=='ADVANTAGE'


def test_attack_bonus_removal_does_not_grant_sight(monkeypatch):
    from combat import ext
    e = duel([])
    attacker, defender = e.state.actors[ME], e.state.actors[FOE]
    condition(e, attacker, 'condition:typed.invisible')
    condition(e, defender, 'condition:core.dodge')
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'attack_mode_removed', [lambda *args: ['ADVANTAGE']])
    assert not target_knowledge.can_see(e, defender, attacker)
    assert e._attack_mode(attacker, defender) == 'NORMAL'


@pytest.mark.parametrize('invisible,dodge,expected',[(False,True,'DISADVANTAGE'),(True,False,'ADVANTAGE'),(True,True,'ADVANTAGE')])
def test_actual_table_weapon_attack_against_dodge_reloads_and_replays(tmp_path,invisible,dodge,expected):
    talent='tianxia.talent.illusion.greater_invisibility'
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.jian','quantity':1}]}}
    combat,table,mid=table_fight(tmp_path,[talent],ally_talents=[],kit=kit)
    # The reviewed spell requires a willing touched creature; cast on an ally.
    attacker, defender = ALLY, RIGHT
    if invisible:
        commit(cast_sender(combat,table,mid,'Greater Invisibility',target=attacker))
    turn(table,mid,attacker)
    assert act(table,mid,'end')['status']=='COMMITTED'
    turn(table,mid,defender)
    if dodge:assert act(table,mid,'system:combat.dodge')['status']=='COMMITTED'
    assert act(table,mid,'end')['status']=='COMMITTED'
    turn(table,mid,attacker)
    state=table.state(mid);menu=state['menu']
    group=next(g for g in menu['actions'] if '.weapon.jian' in g['source_definition_id'] and '#' not in g['source_definition_id'])
    option=next(o for o in group['options'] if defender in o['target_ids'])
    assert table.act(mid,option['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'])['status']=='COMMITTED'
    fresh=CombatService(ROOT,tmp_path)._load_session(mid)
    rolls=[ev for ev in fresh.engine.events if ev.sequence>state['last_sequence'] and ev.event_type=='ATTACK_ROLLED'
           and ev.actor_id==attacker and defender in ev.target_ids]
    assert rolls and all(ev.payload['mode']==expected for ev in rolls)
    assert bool(any(c.condition_id=='condition:typed.invisible' for c in fresh.engine.state.actors[attacker].conditions.values()))==invisible
    assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'


@pytest.mark.parametrize('blindsight,expected', [(False,'DISADVANTAGE'), (True,'DISADVANTAGE')])
def test_table_formation_suppression_uses_shared_perception(monkeypatch, tmp_path, blindsight, expected):
    from tests.test_tabletop_hunt6 import on_hold, HOLD
    from combat.ext import formation_masters
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.jian','quantity':1}]}}
    combat,table,mid=table_fight(tmp_path,[],kit=kit)
    def setup(e):
        attacker,defender=e.state.actors[RIGHT],e.state.actors[LEFT]
        condition(e,attacker,'condition:typed.invisible')
        # The real Radiance formation rider's persisted condition and mask.
        e._apply_condition(attacker,'condition:typed.formation_unlit',
            'tianxia.talent.formations.elemental_killing_array',LEFT,expires_on='UNTIL_REMOVED')
        if blindsight:
            e._apply_condition(defender,senses.SENSE,'test:blindsight',LEFT,
                expires_on='UNTIL_REMOVED',data={'sense':'blindsight','range_ft':30})
    on_hold(monkeypatch,setup)
    assert act(table,mid,HOLD)['status']=='COMMITTED'
    assert act(table,mid,'system:combat.dodge')['status']=='COMMITTED'
    turn(table,mid,RIGHT)
    e=combat._load_session(mid).engine
    attacker,defender=e.state.actors[RIGHT],e.state.actors[LEFT]
    assert formation_masters.masked(e,attacker,defender).get(RIGHT)
    # Round 24's shared perception honors actual condition suppression. A bare
    # attack-mode removal is tested separately and never grants sight.
    assert target_knowledge.can_see(e,defender,attacker)
    before=e.state.model_dump(mode='json')
    assert e._attack_mode(attacker,defender)==expected
    assert e.state.model_dump(mode='json')==before
    state=table.state(mid);menu=state['menu']
    group=next(g for g in menu['actions'] if '.weapon.jian' in g['source_definition_id'] and '#' not in g['source_definition_id'])
    option=next(o for o in group['options'] if LEFT in o['target_ids'])
    assert table.act(mid,option['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'])['status']=='COMMITTED'
    fresh=CombatService(ROOT,tmp_path)._load_session(mid)
    rolls=[ev for ev in fresh.engine.events if ev.sequence>state['last_sequence'] and ev.event_type=='ATTACK_ROLLED'
           and ev.actor_id==RIGHT and LEFT in ev.target_ids]
    assert rolls and all(ev.payload['mode']==expected for ev in rolls)
    assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'
