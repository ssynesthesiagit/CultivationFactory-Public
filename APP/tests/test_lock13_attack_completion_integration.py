"""Conscious-zero survival remains able to attack across integrated guards."""
import pytest
from combat.gate2_runtime_models import ActionDefinition, DiceSpec, EconomyKind
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.test_lock_choices import install
from tests.test_lock9_origins_review import add_hook
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import commit


@pytest.mark.parametrize('kind,count', [('ATTACK',1), ('MULTI_ATTACK',2), ('TYPED',1)])
def test_conscious_zero_paid_attacks_commit_reload_and_replay(monkeypatch, tmp_path, kind, count):
    source = 'test:conscious-attack'
    def compiled(info):
        if info['actor_id'] != H.LEFT:
            return []
        return [ActionDefinition(source_definition_id=source, display_name='Conscious strike',
            owner_id=H.LEFT, economy=EconomyKind.ACTION, resolution_kind=kind,
            target_kind='HOSTILE_ENTITY', reach_ft=5, attack_bonus=20, attack_count=count,
            damage=DiceSpec(count=1,sides=4), damage_type='FORCE', costs=(('resource:core.qi',1),),
            parameters={'typed': {'source':source, 'numbers':{'attack_bonus':20},
                'effects':[{'type':'attack','attack_kind':'cultivation_melee','on_hit':[
                    {'type':'damage','dice':{'count':1,'sides':4},'damage_types':['FORCE']}]}]}})]
    add_hook(monkeypatch, 'compile_actions', compiled)
    install(monkeypatch, 'zero_hp', lambda e,a,*args: 'CONSCIOUS' if a.entity_id == H.LEFT else None)
    add_hook(monkeypatch, 'attack_completed', lambda *args: None)
    install(monkeypatch, 'd20_result', lambda *args: {'source_id':'test:roll','operation':'replace','natural_result':20})
    combat, table, mid = H.table_fight(tmp_path, [])
    def survive(e):
        a = e.state.actors[H.LEFT]
        e._commit_damage(a, a.current_hp, 'FORCE', 'test:drop', H.RIGHT, None, reaction_depth=0)
    H.on_hold(monkeypatch, survive)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[H.LEFT]
    assert actor.current_hp == 0 and actor.life_state == 'CONSCIOUS'
    qi = actor.resources['resource:core.qi']
    c = next(c for c in engine.legal_candidates() if c.source_definition_id == source)
    sequence = table.state(mid)['last_sequence']
    commit(lambda answers=(): table.act(mid,c.candidate_id,c.decision_id,c.state_version,sequence,list(answers)))
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[H.LEFT]
    rolls = [ev for ev in loaded.engine.events if ev.event_type == 'ATTACK_ROLLED' and ev.source_definition_id == source]
    assert len(rolls) == count
    assert actor.current_hp == 0 and actor.life_state == 'CONSCIOUS'
    assert actor.resources['resource:core.qi'] == qi - 1
    assert loaded.engine.state.actors[H.RIGHT].current_hp < loaded.engine.state.actors[H.RIGHT].maximum_hp
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
