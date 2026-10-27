"""MGR-T15 Dampen Sound: production outside-listener route, native reload and gates.

The outside hearing-only Perception consumer is reached only through the ordinary
"Listen for sound inside a dampened zone" action (no injected scene action).
"""
import pytest

from combat.canonical import canonical_sha256
from combat.gate4_adapters import ManualControllerAdapter
from tests.worker2_support import OWNER, ALLY, fixture, candidate, reload, settle, turn
from tests.test_mgr_t14_sound_base import DAMPEN, cast

NAME = 'Listen for sound inside a dampened zone'


def listen_candidates(combat, mid):
    engine = combat._load_session(mid).engine
    return [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == NAME]


def test_listen_route_dormant_without_live_zone(tmp_path):
    combat, table, mid = fixture(tmp_path, [DAMPEN], ally_position={'x': 7, 'y': 6})
    turn(table, mid, ALLY)
    assert not listen_candidates(combat, mid)


def test_listen_route_dormant_for_interior_listener(tmp_path):
    combat, table, mid = fixture(tmp_path, [DAMPEN], ally_position={'x': 2, 'y': 6})
    cast(combat, table, mid)
    turn(table, mid, OWNER)
    assert not listen_candidates(combat, mid)


@pytest.mark.parametrize('mode', ['LOCAL_AUTO'])
def test_outside_listener_gets_disadvantage_from_production_route(tmp_path, monkeypatch, mode):
    combat, table, mid = fixture(tmp_path, [DAMPEN], ask=False, ally_position={'x': 7, 'y': 6})
    cast(combat, table, mid)
    assert reload(tmp_path, mid).state.zones
    turn(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode=mode)
    c = candidate(combat, mid, NAME)
    monkeypatch.setattr(combat.controller, 'choose_primary_action',
        lambda context: ManualControllerAdapter(lambda _: (c.candidate_id, ())).choose_primary_action(context))
    payload = {'actor_id': c.actor_id, 'decision_id': c.decision_id, 'state_version': c.state_version,
               'candidate_id': c.candidate_id, 'target_ids': list(c.target_ids), 'option_ids': [],
               'destination': None}

    def send(answers):
        return table.auto_step(mid, 0, answers)

    before = reload(tmp_path, mid)
    result, answers = send([]), []
    for source, option in [('choice:needle.listen_source', OWNER), ('choice:needle.scene_gm_dc', '0'),
                           ('choice:needle.scene_gm_dc', 'done')]:
        assert result['status'] == 'REACTION_REQUIRED', result
        context = result['reaction']['context']
        assert context['reaction_source_id'] == source
        assert len(reload(tmp_path, mid).rolls) == len(before.rolls)
        answers.append({**{k: context[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id')},
                        'selection': 'USE', 'option_ids': [option]})
        result = send(answers)
    assert result['status'] == 'COMMITTED', result
    e = reload(tmp_path, mid)
    check = next(v for v in reversed(e.events) if v.event_type == 'CHECK_ROLLED')
    assert check.payload['actor']['mode'] == 'DISADVANTAGE'
    assert check.payload['check_metadata'] == {'purpose': 'notice_sound', 'senses': ['hearing'],
        'source_actor_id': OWNER, 'observer_id': ALLY}
    assert check.payload['dc'] == 0

def _large_owner(bundles):
    """Owner is a Large (2x2-cell) creature, so a source can straddle a zone edge."""
    for bundle in bundles:
        if bundle['actor_id'] == OWNER:
            bundle['actor_template']['size_category'] = 'Large'
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_listener_outside_second_zone_hears_inside_it(tmp_path, monkeypatch):
    """Two casters, two cubes: OWNER stands inside zone A (at 3,6) and outside zone B (ALLY's
    cube at 7,6). ALLY's sound source is inside B, so OWNER must be offered Listen and get
    Disadvantage, through the table: commit, cold reload, native roll."""
    combat, table, mid = fixture(tmp_path, [DAMPEN], ally_talents=[DAMPEN], ask=False, ally_position={'x': 7, 'y': 6})
    cast(combat, table, mid)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Dampen Sound', at=(7, 6)).candidate_id)
    assert len(reload(tmp_path, mid).state.zones) == 2
    turn(table, mid, OWNER)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    c = candidate(combat, mid, NAME)
    monkeypatch.setattr(combat.controller, 'choose_primary_action',
        lambda context: ManualControllerAdapter(lambda _: (c.candidate_id, ())).choose_primary_action(context))
    result, answers = table.auto_step(mid, 0, []), []
    for source, option in [('choice:needle.listen_source', ALLY), ('choice:needle.scene_gm_dc', '0'),
                           ('choice:needle.scene_gm_dc', 'done')]:
        assert result['status'] == 'REACTION_REQUIRED', result
        context = result['reaction']['context']
        assert context['reaction_source_id'] == source
        answers.append({**{k: context[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id')},
                        'selection': 'USE', 'option_ids': [option]})
        result = table.auto_step(mid, 0, answers)
    assert result['status'] == 'COMMITTED', result
    e = reload(tmp_path, mid)
    check = next(v for v in reversed(e.events) if v.event_type == 'CHECK_ROLLED')
    assert check.payload['actor']['mode'] == 'DISADVANTAGE'
    assert check.payload['check_metadata'] == {'purpose': 'notice_sound', 'senses': ['hearing'],
        'source_actor_id': ALLY, 'observer_id': OWNER}


def test_straddling_source_disadvantage_matches_listen_offer(tmp_path):
    """One containment rule: a source offered by Listen (any overlap with the zone) is the same source
    that dampening_mode penalises. Scan source positions around the zone edge; the mode must follow
    zone_contains for every position, including a creature that only partly overlaps the zone."""
    from combat.gate2_runtime_models import Position
    from combat.spatial_areas import zone_contains, zone_contains_cells
    from combat.ext.sound_strikes import dampening_mode, dampening_zones
    combat, table, mid = fixture(tmp_path, [DAMPEN], ask=False, ally_position={'x': 7, 'y': 6},
                                 bundle_transform=_large_owner)
    cast(combat, table, mid)
    engine = combat._load_session(mid).engine
    zones = list(dampening_zones(engine))
    assert zones
    listener = engine.state.actors[ALLY]
    owner = engine.state.actors[OWNER]
    meta = {'purpose': 'notice_sound', 'senses': ['hearing'], 'observer_id': ALLY, 'source_actor_id': OWNER}
    checked = straddling = 0
    for x in range(0, 12):
        for y in range(2, 11):
            owner.position = Position(x=x, y=y, z=0)
            if any(zone_contains(engine, listener, zone) for zone in zones):
                continue
            inside = any(zone_contains(engine, owner, zone) for zone in zones)
            touching = [any(zone_contains_cells(engine, [cell], zone) for zone in zones)
                        for cell in engine._actor_volume(owner)]
            straddling += inside and not all(touching)
            expected = 'DISADVANTAGE' if inside else None
            assert dampening_mode(engine, listener, 'WIS', 'Perception', meta) == expected, (x, y)
            checked += 1
    assert checked and straddling



def deafen_ally(combat, monkeypatch):
    """Test setup: ALLY is Deafened (condition:typed.deafened, until removed). Applied whenever the
    saved fight loads, so the condition is what the table commits and reloads, not an in-memory tweak."""
    from combat.gate2_runtime_models import ConditionInstance
    original = combat._load_session

    def loaded(match_id):
        session = original(match_id)
        actor = session.engine.state.actors[ALLY]
        key = f'condition-instance:condition:typed.deafened:{ALLY}:test'
        if key not in actor.conditions:
            actor.conditions[key] = ConditionInstance(instance_id=key, condition_id='condition:typed.deafened',
                source_definition_id='TEST_DEAFENED', source_actor_id=ALLY, target_id=ALLY, applied_sequence=0)
        return session
    monkeypatch.setattr(combat, '_load_session', loaded)


def test_deafened_listener_cannot_succeed_at_listen(tmp_path, monkeypatch):
    """Deafened (cant_hear) ALLY stands outside OWNER's cube; OWNER stands inside it. Listen must not offer
    a hearable source, and no hearing check may roll for ALLY, through commit and cold reload."""
    combat, table, mid = fixture(tmp_path, [DAMPEN], ask=False, ally_position={'x': 7, 'y': 6})
    cast(combat, table, mid)
    assert reload(tmp_path, mid).state.zones
    turn(table, mid, ALLY)
    deafen_ally(combat, monkeypatch)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    c = candidate(combat, mid, NAME)
    monkeypatch.setattr(combat.controller, 'choose_primary_action',
        lambda context: ManualControllerAdapter(lambda _: (c.candidate_id, ())).choose_primary_action(context))
    result, answers, asked = table.auto_step(mid, 0, []), [], []
    dc_answers = iter(['0', 'done'])
    for _ in range(8):
        if result['status'] != 'REACTION_REQUIRED':
            break
        context = result['reaction']['context']
        source = context['reaction_source_id']
        asked.append(source)
        option = OWNER if source == 'choice:needle.listen_source' else next(dc_answers)
        answers.append({**{k: context[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id')},
                        'selection': 'USE', 'option_ids': [option]})
        result = table.auto_step(mid, 0, answers)
    assert result['status'] == 'COMMITTED', result
    e = reload(tmp_path, mid)
    assert any(x.condition_id == 'condition:typed.deafened' for x in e.state.actors[ALLY].conditions.values())
    assert 'choice:needle.listen_source' not in asked, 'a Deafened listener was offered a source it cannot hear'
    hearing = [v for v in e.events if v.event_type == 'CHECK_ROLLED'
               and (v.payload.get('check_metadata') or {}).get('purpose') == 'notice_sound']
    assert hearing == [], 'a Deafened listener rolled a hearing check'

