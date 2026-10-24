"""Unknown attack provenance must not fabricate a Granted Attack restriction."""
import copy

from combat import typed_executor as te
from combat import typed_reactions as tr
from tests.hunt12_support import hit_dice
from tests.worker2_support import OWNER, FOE, reload, settle, turn
from tests.test_tabletop_hunt6 import on_hold
from tests.test_mgr_t14_heron_review_options import fight, hold_id, admitted_unarmed_default, grant_opportunity


def test_unclassified_legacy_hit_does_not_lose_white_wing_attack_ending(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = fight(tmp_path)

    def legacy_hit(engine):
        actor, target = engine.state.actors[OWNER], engine.state.actors[FOE]
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == OWNER and a.display_name == 'Ji (Halberd) attack')
        typed = copy.deepcopy(action.parameters['typed'])
        # A legacy delivery positively identifies the real weapon, but has no
        # root-action/grant classification. Absence must stay unknown.
        typed.pop('source', None)
        typed['weapon_source_id'] = action.source_definition_id
        attack = copy.deepcopy(typed['effects'][0])
        attack['count'] = 1
        attack.pop('count_by_cl', None)
        typed['effects'] = [attack]
        from combat.attack_declaration import ordinary_attack_action, is_granted_attack
        assert not ordinary_attack_action(engine, actor, action, typed)
        assert not is_granted_attack(engine, actor, action, typed)
        te.run_effects(te.Context(engine, actor, action, engine._active_intent, typed, [target], target, {}), [attack])

    on_hold(monkeypatch, legacy_hit)
    prompts = settle(table, mid, hold_id(combat, mid), choices={
        'choice:needle.white_wing_move': ['cell:5,6'],
        'choice:needle.white_wing_result': ['attack'],
        'choice:needle.white_wing_target': 'first',
        'choice:needle.herons_passing_cut': None,
    })
    result = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.white_wing_result')
    assert {o['id'] for o in result['choice']['options']} == {'attack', 'push', 'prone', 'ac'}
    engine = reload(tmp_path / 'fight', mid)
    assert len([e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]) == 2


def test_automatic_reactor_keeps_legal_unarmed_default(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = fight(tmp_path, transform=admitted_unarmed_default)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')

    on_hold(monkeypatch, grant_opportunity)
    settle(table, mid, hold_id(combat, mid), choices={'choice:needle.opportunity_profile': ['0']})
    engine = reload(tmp_path / 'fight', mid)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(attacks) == 1 and attacks[0].source_definition_id.endswith('.opportunity_attack')
