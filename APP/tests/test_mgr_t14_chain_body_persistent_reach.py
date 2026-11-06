"""Thousand-Link Network uses current condition-bound reach (Adamant Guardian +5 ft) for terrain and Opportunity Attacks.

Turn-only Chain Body reach is not used for the out-of-turn trigger. Table admission, native tether, cold reload.
"""
from combat.ext import chain_tethers
from tests import test_mgr_t14_heaven_binding_chain_body_floor58 as support
from tests.test_lock2_persistence import act
from combat import ext
from combat.gate2_runtime_models import ActionDefinition, EconomyKind


def add_self_action(monkeypatch, actor_id, source, effects):
    """A self-targeted typed action (Adamant's +5 ft is granted to its owner, not an enemy)."""
    ext.effects()
    previous = list(ext._HOOKS.get('compile_actions', ()))

    def compile_action(info):
        if info['actor_id'] != actor_id:
            return None
        return [ActionDefinition(source_definition_id=source, display_name='Test self action',
            owner_id=actor_id, economy=EconomyKind.NONE, resolution_kind='TYPED',
            target_kind='SELF', range_ft=5,
            parameters={'typed': {'source': source, 'numbers': info['numbers'], 'effects': effects,
                                  'duration': {'kind': 'instant'}}})]

    monkeypatch.setitem(ext._HOOKS, 'compile_actions', [*previous, compile_action])

OWNER, TARGET = support.OWNER, support.TARGET
ZONE = 'zone:derived:thousand_link:' + OWNER


def _zone_cells(engine):
    zone = next(z for z in chain_tethers.tether_ground(engine) if z.zone_id == ZONE)
    return {(c.x, c.y) for c in zone.affected_cells}


def test_adamant_reach_extends_network_terrain_and_oa_trigger_after_reload(tmp_path, monkeypatch):
    # Owner at (3,4) with a 5-ft chain; target tethered at (3,5). Its step to (3,6) is 10 ft from the owner:
    # outside the 5-ft base reach, inside base + Adamant's +5 ft.
    # Actions compile at match creation, so the self-buff is registered before the fight.
    add_self_action(monkeypatch, OWNER, 'test:adamant_reach', [{'type': 'guardian_adamant'}])
    service, table, mid = support.acquired_fight(tmp_path, ['chain_body_integration', 'thousand_link_meridian_network'],
                                                 target_at=(3, 5), ask_reactions=True)
    support.native_tether(service, table, mid)
    support.commit(table, mid, 'test:adamant_reach')
    assert act(table, mid, 'end')['status'] == 'COMMITTED'

    engine = support.cold(service, mid)
    owner = engine.state.actors[OWNER]
    # Out of turn: the 5-ft chain plus the persistent +5 ft; the turn-only Chain Body bonus is not added.
    assert chain_tethers.chain_reach(engine, owner) == 10
    assert (3, 6) in _zone_cells(engine)

    state = table.state(mid)
    menu = state['menu']
    assert menu['actor_id'] == TARGET
    move = next(m for m in menu['moves'] if m['destination'] == {'x': 3, 'y': 6})
    answers = []
    for _ in range(24):
        result = table.act(mid, move['candidate_id'], menu['decision_id'], menu['state_version'],
                           state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'USE'}
        if prompt.get('choice'):
            answer['option_ids'] = [prompt['choice']['options'][0]['id']]
        answers.append(answer)
    assert result['status'] == 'COMMITTED'

    engine = support.cold(service, mid)
    assert not engine.state.actors[OWNER].reaction_available
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER
               and e.sequence > state['last_sequence']]
    assert len(attacks) == 1
    assert sum('LEAVE_REACH' in str(answer.get('checkpoint', '')) for answer in answers) == 1
    assert chain_tethers.chain_reach(engine, engine.state.actors[OWNER]) == 10
    assert (3, 6) in _zone_cells(engine)
