"""Live table and model projections for the Bell review's information findings."""
import pytest
from combat import observer_information as information
from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
from combat.gate4_context import build_decision_context
from combat.typed_executor import check_mode
from tests.worker2_support import fixture, candidate, reload, settle, turn, OWNER, ALLY, FOE


def test_vertical_direction_uses_the_shared_plain_text_vocabulary():
    from combat.gate2_runtime_models import Position
    from combat.information_results import describe
    direction = information.direction(Position(x=0, y=1), Position(x=1, y=0, z=2))
    assert direction == 'northeast and above'
    text = describe(None, None, [{'kind': 'reading_direction', 'direction': direction,
                                 'ability': 'Watch Bell'}])[0]
    assert 'northeast' in text and 'above' in text


def cast(combat, table, mid, name, choices=None, **target):
    return settle(table, mid, candidate(combat, mid, name, **target).candidate_id, picks=choices or {})


def own_model_information(combat, engine):
    policy, _ = combat.policies.for_actor(OWNER)
    return list(build_decision_context(engine, policy, for_ai=True).information)


def test_private_bell_direction_reaches_table_and_model_without_sharing_identifiers(tmp_path):
    combat, table, mid = fixture(tmp_path, ['tianxia.talent.illusion.greater_invisibility'],
        owner_features=[bell.WATCH], ally_talents=[bell.WATCH], cl=18, named=True)
    cast(combat, table, mid, 'Greater Invisibility', target=ALLY)
    cast(combat, table, mid, 'Watch Bell', {
        'choice:needle.bell_warning_tone': 'revealing',
        'choice:needle.bell_reveal_target': ALLY})
    engine = reload(tmp_path, mid)
    state = table.state(mid)
    own = state['fog_perception'][OWNER]
    assert any(f['kind'] == 'reading_direction' and f['direction'] == 'east'
        for f in own['information'])
    assert any('marked' in line and 'east' in line for line in own['information_text'])
    assert not any(f['kind'] == 'reading_direction'
        for f in state['fog_perception'][ALLY].get('information', []))
    facts = own_model_information(combat, engine)
    assert any(f['kind'] == 'reading_direction' for f in facts)
    assert not any('source_instance' in f or 'target_id' in f for f in facts)
    assert not any('maximum HP' in line for line in own['information_text'])


def make_effect(tmp_path, *, zone=False, seed='BELL-RESONANCE-0', wall=False, owner_dc=16):
    def battlefield(document):
        if wall:
            document['terrain_regions'].append({'region_id': 'test:opaque',
                'terrain_type': 'BLOCKED', 'movement_cost': 1, 'description': 'Opaque stone screen',
                'height_ft': 100, 'cells': [{'x': 5, 'y': y} for y in range(document['height_squares'])]})
    combat, table, mid = fixture(tmp_path, [] if zone else ['tianxia.talent.illusion.greater_invisibility'],
        owner_features=[bell.WATCH], ally_talents=['TAL_ILLUSION_MINOR_ILLUSION'] if zone else [],
        cl=18, owner_pb=6, owner_dc=owner_dc, named=True, seed=seed, battlefield_transform=battlefield)
    if zone:
        turn(table, mid, ALLY)
        cast(combat, table, mid, 'Minor Illusion',
            {'choice:needle.minor_detail': 'image'}, at=(4, 5))
        turn(table, mid, OWNER)
    else:
        cast(combat, table, mid, 'Greater Invisibility', target=ALLY)
    engine = reload(tmp_path, mid)
    entry = next(s for s in information.sources(engine)
        if ('zone' in s if zone else s['holder_id'] == ALLY and 'invisible' in s['tags']))
    cast(combat, table, mid, 'Watch Bell', {
        'choice:needle.bell_warning_tone': 'revealing',
        'choice:needle.bell_reveal_target': bell.effect_option(engine, engine.state.actors[OWNER], entry)})
    return combat, table, mid, entry


@pytest.mark.parametrize('zone', [False, True])
def test_successful_effect_revelation_is_visible_to_an_independent_observer(tmp_path, zone):
    successes = 0
    for index in range(3):
        root = tmp_path / str(index)
        combat, table, mid, source = make_effect(root, zone=zone, seed='BELL-RESONANCE-' + str(index))
        engine = reload(root, mid)
        rolls = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'
            and e.payload.get('check') == 'Revealing Tone Cultivation Check']
        assert rolls
        if not any(bell.held(a, 'resonance') for a in engine.state.actors.values()):
            continue
        successes += 1
        state = table.state(mid)
        facts = state['fog_perception'][FOE]['information']
        assert any(f['kind'] == 'reading_resonance' and f.get('position') == source['position'].model_dump(mode='json')
            for f in facts)
        assert any('resonance' in line for line in state['fog_perception'][FOE]['information_text'])
        assert not any('source_instance' in f for f in facts)
        if not zone:
            assert any(c.condition_id == 'condition:typed.invisible'
                for c in engine.state.actors[ALLY].conditions.values())
            assert bell.marked_visibility(engine, engine.state.actors[FOE], engine.state.actors[ALLY]) is None
    assert successes, 'fixed seeds must exercise a successful committed revelation'


def test_resonance_does_not_broadcast_through_an_opaque_wall(tmp_path):
    exercised = 0
    for index in range(3):
        root = tmp_path / str(index)
        combat, table, mid, source = make_effect(root, zone=True, wall=True, seed='BELL-RESONANCE-' + str(index))
        engine = reload(root, mid)
        if not any(bell.held(a, 'resonance') for a in engine.state.actors.values()):
            continue
        exercised += 1
        state = table.state(mid)
        assert any(f['kind'] == 'reading_resonance'
            for f in state['fog_perception'][ALLY].get('information', []))
        assert not any(f['kind'] == 'reading_resonance'
            for f in state['fog_perception'][FOE].get('information', []))
    assert exercised


def test_failed_revelation_reaches_own_table_and_model_with_no_location(tmp_path):
    exercised = 0
    for index in range(4):
        root = tmp_path / str(index)
        combat, table, mid, source = make_effect(root, seed='BELL-FAILED-' + str(index), owner_dc=100)
        engine = reload(root, mid)
        if not bell.held(engine.state.actors[OWNER], 'failed_revelation'):
            continue
        exercised += 1
        state = table.state(mid)
        own = state['fog_perception'][OWNER]
        finding = next(f for f in own['information'] if f['kind'] == 'reading_concealment_exists')
        assert set(finding) == {'kind', 'ability'}
        assert any('check failed' in line and 'concealed' in line for line in own['information_text'])
        assert finding in own_model_information(combat, engine)
        assert not any(f['kind'] == 'reading_concealment_exists'
            for f in state['fog_perception'][FOE].get('information', []))
    assert exercised, 'fixed seeds must exercise a failed committed revelation'


@pytest.mark.parametrize('source_cl,trace', [(10, True), (18, False), (20, False)])
def test_protected_watch_projects_traces_around_native_visual_illusions(tmp_path, source_cl, trace):
    from tests.h1_support import sheet
    combat, table, mid = fixture(tmp_path, [], owner_features=[bell.FORM], cl=18, named=True,
        foe_sheet=sheet(['TAL_ILLUSION_MINOR_ILLUSION'], cl=source_cl, name='Mara'))
    cast(combat, table, mid, 'Begin Bell-Tower Formation',
        {'choice:needle.bell_protected_allies': [OWNER, ALLY]})
    # Use the real ritual/turn clock. The fixture lasts fifteen rounds.
    for _ in range(30):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert list(bell.placed.of(reload(tmp_path, mid), bell.FORM_TAG))
    turn(table, mid, FOE)
    cast(combat, table, mid, 'Minor Illusion',
        {'choice:needle.minor_detail': 'image'}, at=(4, 5))
    engine = reload(tmp_path, mid)
    image = next(z for z in engine.state.zones.values() if bell.placed.data(z).get('tag') == 'figment')
    source = next(s for s in information.sources(engine) if s['id'] == image.zone_id)
    assert 'visual_illusion' in source['tags'] and source['cl'] == source_cl
    state = table.state(mid)
    own = state['fog_perception'][OWNER]
    rows = [f for f in own.get('information', []) if f['kind'] == 'reading_trace']
    assert bool(rows) is trace
    if trace:
        assert rows[0]['position'] == image.center.model_dump(mode='json')
        assert any('traces' in line for line in own['information_text'])
    assert not any(f['kind'] == 'reading_trace'
        for f in state['fog_perception'][FOE].get('information', []))
