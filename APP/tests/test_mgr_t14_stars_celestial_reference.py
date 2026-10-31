"""Native acquired Stars -> GM reference -> table attack -> cold replay.

The GM supplies the explicit external adjudication the Open Sky rule requires;
damage, recipient legality, movement and ownership remain native mechanics.
"""
import pytest

from combat.ext.stars_celestial_reference import SOURCE, KIND, SCOPE
from tests.test_mgr_t14_starbolt_base import native_fight
from tests.auto_worker1_support import LEFT, RIGHT, act, reload, resolve, cell_send


def declaration(engine, accepted=1, reference_kind='clear_window'):
    return {'source': SOURCE, 'subject': LEFT, 'kind': KIND, 'scope': SCOPE,
        'value': {'reference_kind': reference_kind, 'reference_name': 'North observatory window',
            'accepted': accepted, 'position': engine.state.actors[LEFT].position.model_dump(mode='json')},
        'expires_at': (engine.state.round_number - 1) * 6 + 60, 'readers': []}


def far_options(table, mid):
    return [option for group in table.state(mid)['menu']['actions']
        if group['label'].startswith('Starbolt') for option in group['options']
        if RIGHT in option.get('target_ids', [])]


@pytest.mark.parametrize('reference_kind', ['direct_sky', 'clear_window', 'mirror_pool', 'observatory_lens'])
def test_gm_accepted_reference_enables_actual_aligned_starbolt_and_cold_replay(tmp_path, reference_kind):
    combat, table, mid = native_fight(tmp_path,
        positions={LEFT: {'x': 0, 'y': 1}, RIGHT: {'x': 19, 'y': 1}})
    assert not far_options(table, mid)
    engine = reload(combat, mid)
    from combat import targeting, senses
    assert senses.perceives(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT])
    assert targeting.line_of_effect(engine, engine.state.actors[LEFT], target=engine.state.actors[RIGHT])
    combat.declare_combat_world_fact(mid, state_version=engine.state.state_version,
        payload=declaration(engine, reference_kind=reference_kind))
    assert far_options(table, mid)
    resolve(lambda answers: act(table, mid, 'Starbolt (Aligned: +30 ft)', answers, target_id=RIGHT))
    session = combat._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    assert session.engine.state.actors[RIGHT].current_hp < 1000


def test_rejected_replaced_moved_and_wrong_owner_references_grant_nothing(tmp_path):
    combat, table, mid = native_fight(tmp_path,
        positions={LEFT: {'x': 0, 'y': 1}, RIGHT: {'x': 19, 'y': 1}})
    engine = reload(combat, mid)
    doc = declaration(engine)
    with pytest.raises(ValueError):
        combat.declare_combat_actor_fact(mid, LEFT, state_version=engine.state.state_version, payload=doc)
    with pytest.raises(ValueError):
        combat.declare_combat_world_fact(mid, state_version=engine.state.state_version,
            payload={**doc, 'subject': RIGHT})
    with pytest.raises(ValueError):
        combat.declare_combat_world_fact(mid, state_version=engine.state.state_version,
            payload={**doc, 'value': {**doc['value'], 'reference_kind': []}})
    combat.declare_combat_world_fact(mid, state_version=engine.state.state_version, payload=doc)
    assert far_options(table, mid)
    engine = reload(combat, mid)
    combat.declare_combat_world_fact(mid, state_version=engine.state.state_version,
        payload=declaration(engine, accepted=0))
    assert not far_options(table, mid)
    engine = reload(combat, mid)
    combat.declare_combat_world_fact(mid, state_version=engine.state.state_version,
        payload=declaration(engine))
    # Moving farther away keeps the target beyond ordinary range. The reference
    # belongs to the old location; movement does not grant a traveling sky lens.
    resolve(cell_send(table, mid, 'Move', (0, 2)))
    assert not far_options(table, mid)
    session = combat._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
