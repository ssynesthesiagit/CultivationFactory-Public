"""Kindled Hearth's journey choices are the offered menu options, not a hand-built payload."""
from tests.test_redo_hearthfire_recovery import game, A, B, HEARTH


def kindle_options(cold, jid, actor=A):
    return [o for o in cold().journey_menu(jid, actor)['options'] if o['kind'] == 'hearth_kindle']


def protected_names(label):
    """The guests a Hearth choice says it protects, as printed in its label."""
    return label.split('protecting ', 1)[1].rsplit(' within 15 feet', 1)[0]


def test_journey_menu_offers_far_placement_and_chosen_guest_and_command_accepts_it(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    options = kindle_options(cold, jid)
    # Beyond the owner's square and its neighbours: 20 feet away, with both creatures.
    # Subsets follow the session's persisted actor order, so compare recipient sets.
    far = [o for o in options if o['payload']['position'] == {'x': 5, 'y': 1}
           and set(o['payload']['recipients']) == {A, B}]
    assert len(far) == 1, 'every legal placement within 30 feet with each chosen guest must be offered'
    assert any(o['payload']['position'] == {'x': 5, 'y': 1}
               and set(o['payload']['recipients']) == {A} for o in options)
    # Choosing only the other creature is legal too; the owner is not implicit.
    assert any(o['payload']['position'] == {'x': 5, 'y': 1}
               and set(o['payload']['recipients']) == {B} for o in options)
    state = act(far[0]['kind'], far[0]['payload'])
    hearth = state['actors'][A]['travel_effects'][HEARTH]
    assert (hearth['position']['x'], hearth['position']['y']) == (5, 1)
    assert set(hearth['recipients']) == {A, B}
    assert cold().journey_state(jid) == state


def test_every_choice_label_names_the_actual_guests_in_their_order(tmp_path, monkeypatch):
    """A two-creature choice names both creatures, whichever one persisted first."""
    cold, jid, act = game(tmp_path, monkeypatch)
    names = {A: 'hearthkeeper', B: 'guest'}
    options = [o for o in kindle_options(cold, jid) if o['payload']['position'] == {'x': 5, 'y': 1}]
    assert options
    for option in options:
        recipients = option['payload']['recipients']
        expected = ('no one' if not recipients
                    else ' and '.join(names[aid] for aid in recipients))
        assert protected_names(option['label']) == expected, option['label']
    both = [o for o in options if set(o['payload']['recipients']) == {A, B}]
    assert both and 'hearthkeeper' in protected_names(both[0]['label']) \
        and 'guest' in protected_names(both[0]['label'])
