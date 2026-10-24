"""Ascetic Body on a journey: a four-hour meditation Long Rest, and no hunger, thirst or cold wearing the traveller down."""
import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.h1_support import ROOT, sheet

A = FACTORY_ACTOR_PREFIX + 'traveller'
B = FACTORY_ACTOR_PREFIX + 'companion'
ASCETIC = 'tianxia.subpath.body.yamabushi.feature.ascetic_body'


def game(tmp_path, monkeypatch, *, ascetic=True):
    monkeypatch.setattr(CombatService, '_factory_owner_sheet',
                        lambda self, pid: sheet([ASCETIC] if ascetic and pid == 'traveller' else [], cl=15, name=pid))
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'scene': {
        'stable_id': 'journey:test', 'width_squares': 20, 'height_squares': 5, 'square_size_ft': 5,
        'starting_positions': {}, 'terrain_regions': []}})
    service = CombatService(ROOT, tmp_path)
    jid = service.create_journey(project_ids=['traveller', 'companion'], arena_id='scene',
                                 positions={A: {'x': 0, 'y': 1}, B: {'x': 0, 'y': 2}},
                                 base_paces={A: 5, B: 5}, control_modes={A: 'MANUAL'})['journey_id']

    def act(kind, payload=None):
        fresh = CombatService(ROOT, tmp_path)
        return fresh.journey_act(jid, fresh.journey_state(jid)['revision'], A, kind, payload or {})

    return (lambda: CombatService(ROOT, tmp_path)), jid, act


def test_meditation_completes_a_long_rest_in_four_hours(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    assert any(o['kind'] == 'meditative_rest' for o in cold().journey_menu(jid, A)['options'])
    before = cold().journey_state(jid)
    state = act('meditative_rest')
    assert state['seconds'] - before['seconds'] == 4 * 3600
    assert state['actors'][A]['long_rests'] == before['actors'][A]['long_rests'] + 1
    assert state['events'][-1]['kind'] == 'LONG_REST'


def test_others_cannot_meditate_a_long_rest(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch, ascetic=False)
    assert not any(o['kind'] == 'meditative_rest' for o in cold().journey_menu(jid, A)['options'])
    with pytest.raises(ValueError):
        act('meditative_rest')


@pytest.mark.parametrize('ascetic,levels', [(True, 0), (False, 1)])
def test_ordinary_hunger_and_cold_do_not_exhaust_an_ascetic(tmp_path, monkeypatch, ascetic, levels):
    cold, jid, act = game(tmp_path, monkeypatch, ascetic=ascetic)
    assert act('travel_exhaustion', {'levels': 1, 'ordinary': True})['actors'][A]['exhaustion'] == levels
