"""Service regressions for journey check projection, arithmetic and decision labels."""
from tests.test_journey_rolls import A, B, HEART, game, task, events


def test_pending_window_only_visible_to_owner_in_both_projections(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART])
    task(admit, 'private', known=False)
    result = act('roll_check', {'task': 'private'})
    window = result['actors'][A]['pending_roll']
    assert window['dc'] is None and window['natural'] and window['offers']
    assert cold().journey_state(jid, A)['actors'][A]['pending_roll'] == window
    assert 'pending_roll' not in cold().journey_state(jid, B)['actors'][A]


def test_sect_check_requires_choice_and_uses_chosen_ability_and_proficiency(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, spheres=['tianxia.sphere.sect_stewardship'],
                                 wisdom=4, sect_choice=None)
    task(admit, 'petition', dc=10, tags=('sect_check',), ability='STR')
    assert not [o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'roll_check']
    act('sect_key_choice', {'ability': 'WIS'})
    window = act('roll_check', {'task': 'petition'})['actors'][A]['pending_roll']
    assert window['total'] == window['natural'] + 7
    act('roll_decide', {'offer': ''})
    assert events(cold, jid, 'CHECK_RESOLVED')[0]['success'] == int(window['natural'] + 7 >= 10)
    assert cold().journeys.replay(jid)['status'] == 'PASS'


def test_named_checks_and_decisions_identify_creature_and_ability(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART])
    for key, description, tags in [('secret-one', 'Plea for mercy', ['mercy']),
                                    ('secret-two', 'Price negotiation', ['price'])]:
        admit('check_task', {'id': key, 'description': description, 'ability': 'CHA', 'dc': 20,
                             'dc_known': True, 'tags': tags, 'proficient': False})
    labels = [o['label'] for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'roll_check']
    assert len(labels) == 2 and any('Plea for mercy' in x for x in labels)
    assert any('Price negotiation' in x for x in labels)
    assert all('Mediator' in x and 'secret-' not in x for x in labels)
    act('roll_check', {'task': 'secret-one'})
    labels = [o['label'] for o in cold().journey_menu(jid, A)['options']]
    assert all('Mediator' in x and 'Plea for mercy' in x for x in labels)
    assert any('Softened Heart' in x for x in labels)
