"""Kindled Hearth's journey choices are the offered menu options, not a hand-built payload."""
from tests.test_redo_hearthfire_recovery import game, A, B, HEARTH


def test_journey_menu_offers_far_placement_and_chosen_guest_and_command_accepts_it(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    options = [o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'hearth_kindle']
    # Beyond the owner's square and its neighbours: 20 feet away, with a chosen guest.
    far = [o for o in options if o['payload'] == {'position': {'x': 5, 'y': 1}, 'recipients': [A, B]}]
    assert len(far) == 1, 'every legal placement within 30 feet with each chosen guest must be offered'
    assert any(o['payload']['position'] == {'x': 5, 'y': 1} and o['payload']['recipients'] == [A] for o in options)
    state = act(far[0]['kind'], far[0]['payload'])
    hearth = state['actors'][A]['travel_effects'][HEARTH]
    assert (hearth['position']['x'], hearth['position']['y']) == (5, 1)
    assert hearth['recipients'] == [A, B]
    assert cold().journey_state(jid) == state
