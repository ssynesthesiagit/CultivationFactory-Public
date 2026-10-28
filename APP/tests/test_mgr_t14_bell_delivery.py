"""F13 review: a paid Bell-Tower fact must reach the observer it was bought for.

Three deliveries were missing. A paid revelation committed a private reading (a failed
revealing tone's "you know concealment exists", a successful one's resonance) that only
``observer_information.readings`` could see, and nothing called it, so neither the table's
perception projection nor the acting creature's own decision context carried it. Protected
Watch promised chosen allies traces around lower-CL visual Illusions, but the plug-in only
classified creature targets (spirits, possessing entities) and never a native Illusion
source. Ninefold Heavenly Bell promised allies inside its field can hear the bell through
ordinary Silence, and no sound path said so.

Each test drives the printed paid ability through the real table commit and cold reload.
"""
import pytest

from combat import observer_information as information
from combat import senses
from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
from combat.gate4_context import build_decision_context
from tests.h1_support import sheet
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE

ILLUSION = 'TAL_ILLUSION_MINOR_ILLUSION'
SILENCE = 'TAL_SOUND_TRUE_SILENCE'
TRANSMISSION = 'An active supernatural effect is producing visible or audible resonance.'


def cast(combat, table, mid, name, choices):
    return settle(table, mid, candidate(combat, mid, name).candidate_id, picks=choices)


def figment(engine):
    return next(z for z in engine.state.zones.values() if bell.placed.data(z).get('tag') == 'figment')


@pytest.mark.parametrize('kind,dc', [('concealment_exists', 40), ('resonance', 2)])
def test_paid_revelation_reaches_the_observers_table_and_ai_projection(tmp_path, kind, dc):
    """A committed reading must reach the viewer's perception and its own decision context."""
    combat, table, mid = fixture(
        tmp_path, [], owner_features=[bell.WATCH], cl=18, named=True, owner_pb=6,
        foe_sheet=sheet([ILLUSION], cl=18, dc=dc, name='Mara'), seed='BELL-PROJECTION-' + kind)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Minor Illusion', at=(5, 6)).candidate_id,
           picks={'choice:needle.minor_detail': 'image'})
    engine = reload(tmp_path, mid)
    effect = next(s for s in information.sources(engine) if s['id'] == figment(engine).zone_id)
    assert effect['dc'] == dc
    turn(table, mid, OWNER)
    cast(combat, table, mid, 'Watch Bell', {'choice:needle.bell_warning_tone': 'revealing',
         'choice:needle.bell_reveal_target': bell.effect_option(engine, engine.state.actors[OWNER], effect)})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    stored = [c.data for c in owner.conditions.values() if c.condition_id == information.READING]
    assert [row['kind'] for row in stored] == [kind], 'The paid check must settle the branch under test'
    details = {} if kind == 'concealment_exists' else {'text': TRANSMISSION}
    # The table's own perception query for this viewer.
    sensed = senses.perception(engine, owner)
    projected = [r for r in sensed.get('information') or [] if r.get('kind') == kind]
    assert projected and projected[0]['viewer_id'] == OWNER
    assert projected[0]['details'] == details, 'A failed revelation never names a location or nature'
    assert set(projected[0]) == {'kind', 'viewer_id', 'source_id', 'details'}
    if kind == 'resonance':
        assert any(TRANSMISSION in line for line in sensed.get('information_text') or []), \
            'The model seat reads the same wording the table renders'
    # The acting creature's own player/AI seat.
    policy, _ = combat.policies.for_actor(OWNER)
    context = build_decision_context(engine, policy)
    assert context.active_actor_id == OWNER
    assert any(row.get('kind') == kind for row in context.information)
    # Nobody else is told, not even this owner's ally.
    for other in (ALLY, FOE):
        assert not any(r.get('kind') == kind
                       for r in senses.perception(engine, engine.state.actors[other]).get('information') or [])


@pytest.mark.parametrize('source_cl,traced', [(9, True), (18, False)])
def test_protected_watch_shows_chosen_allies_a_lower_cl_visual_illusion(tmp_path, source_cl, traced):
    """Protected Watch promises traces around lower-CL visual Illusions, not only creature targets."""
    combat, table, mid = fixture(
        tmp_path, [], owner_features=[bell.FORM], cl=18, named=True,
        foe_sheet=sheet([ILLUSION], cl=source_cl, name='Mara'), seed='BELL-TRACE-' + str(source_cl),
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 8, 'y': 6}})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Minor Illusion', at=(7, 6)).candidate_id,
           picks={'choice:needle.minor_detail': 'image'})
    turn(table, mid, OWNER)
    cast(combat, table, mid, 'Begin Bell-Tower Formation', {
        'choice:needle.bell_protected_allies': [OWNER, ALLY],
        'choice:needle.bell_anchor_location': 'cell:6,6'})
    for _ in range(30):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    formation = next(z for z in bell.placed.of(engine, bell.FORM_TAG))
    assert set(bell.placed.data(formation)['chosen']) == {OWNER, ALLY}
    ally = engine.state.actors[ALLY]
    traces = [r for r in senses.perception(engine, ally).get('information') or []
              if r.get('kind') == 'resonance' and r.get('source_id') == bell.FORM]
    if not traced:
        assert not traces, 'An Illusion at or above the field CL is not a lower-CL trace'
        return
    assert len(traces) == 1 and traces[0]['viewer_id'] == ALLY
    assert traces[0]['details'] == {'text': 'A visual Illusion leaves a flickering trace here.',
                                   'position': {'x': 7, 'y': 6, 'z': 0}}
    assert any(r['kind'] == 'resonance' for r in senses.perception(engine, engine.state.actors[OWNER])
               .get('information') or []), 'The bell ringer is a chosen ally inside the field too'
    assert not any(r.get('kind') == 'resonance'
                   for r in senses.perception(engine, engine.state.actors[FOE]).get('information') or [])


def test_ninefold_allies_hear_the_bell_through_ordinary_silence(tmp_path):
    """The field's printed grant carries the bell through Silence, and nothing else."""
    from combat.speech import can_hear_from

    combat, table, mid = fixture(tmp_path, [], owner_features=[bell.WATCH, bell.NINE], cl=18,
                                 named=True, foe_sheet=sheet([SILENCE], cl=18, name='Mara'),
                                 seed='BELL-SILENCE')
    # Another creature's ordinary Silence deafens the ally before the field is raised, so the
    # ally is already Deafened when the bell rings.
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'True Silence', at=(4, 6)).candidate_id)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert any(c.condition_id == 'condition:typed.deafened' for c in ally.conditions.values())
    cast(combat, table, mid, 'Ninefold Heavenly Bell', {'choice:needle.bell_protected_allies': [OWNER, ALLY]})
    # One turn: the bell is an action and its tone a bonus action, so no turn start rings the tones.
    cast(combat, table, mid, 'Watch Bell', {'choice:needle.bell_warning_tone': 'guarding',
                                            'choice:needle.bell_guarding': [ALLY]})
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    guarding = bell.held(ally, 'guarding')
    assert guarding, 'A chosen ally inside the field hears the bell through Silence'
    bell_sound = guarding[0].source_definition_id
    assert can_hear_from(engine, engine.state.actors[OWNER], ally, bell_sound), 'The grant is the printed field'
    assert not can_hear_from(engine, engine.state.actors[FOE], ally, bell_sound), 'No other speaker rides it'
    # Ordinary Silence is not itself lifted: the ally is still Deafened outside the field's grant.
    assert any(c.condition_id == 'condition:typed.deafened' for c in ally.conditions.values())


def test_ninefold_grant_names_only_chosen_allies_inside_the_field(tmp_path):
    """An unchosen ally keeps Silence's hold on the bell; the grant is the field's own, for its own allies."""
    from combat.speech import can_hear_from

    combat, table, mid = fixture(tmp_path, [], owner_features=[bell.WATCH, bell.NINE], cl=18,
                                 named=True, foe_sheet=sheet([SILENCE], cl=18, name='Mara'),
                                 seed='BELL-SILENCE-EDGE')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'True Silence', at=(4, 6)).candidate_id)
    turn(table, mid, OWNER)
    cast(combat, table, mid, 'Ninefold Heavenly Bell', {'choice:needle.bell_protected_allies': [OWNER]})
    engine = reload(tmp_path, mid)
    zone = next(z for z in bell.placed.of(engine, bell.NINE_TAG))
    assert zone.active and bell.placed.data(zone)['chosen'] == [OWNER]
    ally = engine.state.actors[ALLY]
    assert bell.fields(engine, ally, bell.NINE_TAG) == []
    assert not can_hear_from(engine, engine.state.actors[OWNER], ally, zone.source_definition_id)
    cast(combat, table, mid, 'Watch Bell', {'choice:needle.bell_warning_tone': 'guarding'})
    engine = reload(tmp_path, mid)
    assert not bell.held(engine.state.actors[ALLY], 'guarding'), 'A creature outside the field stays deaf'


def test_watch_of_the_tower_alert_reaches_the_ringers_own_projection(tmp_path):
    """A Formation field alert is the ringer's own reading, and it is nobody else's."""
    combat, table, mid = fixture(
        tmp_path, [], owner_features=[bell.FORM], cl=18, named=True,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 7, 'y': 6}})
    cast(combat, table, mid, 'Begin Bell-Tower Formation', {
        'choice:needle.bell_protected_allies': [OWNER, ALLY],
        'choice:needle.bell_anchor_location': 'cell:6,6'})
    for _ in range(30):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    # The field's own alert producer: the ring ringer watches the field, not the whole table.
    bell.tower_event(engine, foe, 'audible_technique')
    owner = engine.state.actors[OWNER]
    alerts = [r for r in senses.perception(engine, owner).get('information') or []
              if r.get('kind') == 'field_event']
    assert alerts and alerts[0]['viewer_id'] == OWNER
    assert alerts[0]['details']['event_type'] == 'audible_technique'
    assert alerts[0]['details']['allegiance'] == 'hostile'
    assert not any(r.get('kind') == 'field_event'
                   for r in senses.perception(engine, foe).get('information') or [])
