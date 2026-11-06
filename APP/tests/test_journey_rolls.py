"""The after-roll window of a journey check, through the journey service, with commit and cold reload."""
from copy import deepcopy
import json
import zipfile
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

PID, QID = '0badc0de-1900-4000-8000-000000000001', '0badc0de-1900-4000-8000-000000000002'
A, B = FACTORY_ACTOR_PREFIX + PID, FACTORY_ACTOR_PREFIX + QID
HEART = 'tianxia.talent.beauty.softened_heart'
MERIT = 'resource:sect_stewardship.merit_dice'
MERIT_SIZE = 'resource:sect_stewardship.merit_die_size'
QI = 'resource:core.qi'


def game(tmp_path, monkeypatch, *, talents=(), spheres=(), automatic=False, wisdom=None, sect_choice='CHA', both_owners=False):
    base = sheet([], cl=5, name='Mediator')
    base['identity'].update(proficiency_bonus=3, path_ids=['tianxia.path.qi_cultivation'])
    if wisdom is not None:
        for ability in base['ability_scores_and_statistics']['abilities']:
            if ability['ability'] == 'WIS':
                ability.update(score=18, modifier=wisdom)
    base['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation']}
    service = CombatService(ROOT, tmp_path)
    for pid in (PID, QID):
        path = service.combatant_library.install_root / pid / 'current.zip'
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(base))
    table = TabletopService(service, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    for sphere in spheres:
        table.add_advancement(PID, 'sphere', sphere, gm=True)
    for talent in talents:
        table.add_advancement(PID, 'talent', talent, gm=True)
        if both_owners:
            table.add_advancement(QID, 'talent', talent, gm=True)
    table.save_reactions(PID, {'mode': 'ask'})
    monkeypatch.setattr('combat.journey.secrets.token_hex', lambda n: '190000000000000000000001')
    arena = {'stable_id': 'rolls:hall', 'display_name': 'Hall', 'width_squares': 10, 'height_squares': 8,
             'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'field': deepcopy(arena)})
    state = service.create_journey(project_ids=[PID, QID], arena_id='field',
        positions={A: {'x': 1, 'y': 1}, B: {'x': 8, 'y': 1}}, base_paces={A: 1800, B: 1800},
        control_modes={A: 'LOCAL_AUTO' if automatic else 'MANUAL', B: 'MANUAL'})
    jid = state['journey_id']

    def cold():
        return CombatService(ROOT, tmp_path)

    def act(kind, payload=None, aid=A):
        fresh = cold()
        result = fresh.journey_act(jid, fresh.journey_state(jid)['revision'], aid, kind, payload)
        assert cold().journey_state(jid, viewer_id=aid) == result
        return result

    def admit(kind, payload, aid=A):
        fresh = cold()
        return fresh.journey_admit(jid, fresh.journey_state(jid)['revision'], aid, kind, payload, gm=True,
                                   reason='Scenario owner: the table called for this check.')
    if spheres and sect_choice:
        act('sect_key_choice', {'ability': sect_choice})
    return cold, jid, act, admit


def task(admit, key='plea', *, dc=100, known=True, tags=('mercy',), ability='CHA'):
    admit('check_task', {'id': key, 'description': key, 'ability': ability, 'dc': dc, 'dc_known': known, 'tags': list(tags), 'proficient': False})


def events(cold, jid, kind):
    return [e for e in cold().journeys.load(jid).state['events'] if e['kind'] == kind]


def test_a_manual_owner_decides_after_the_d20_and_nothing_else_until_then(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART])
    task(admit)
    qi = cold().journeys.load(jid).state['actors'][A]['resources'][QI]
    result = act('roll_check', {'task': 'plea'})
    pending = result['actors'][A]['pending_roll']
    assert pending['consumer'] == 'scene_check' and pending['dc'] == 100 and [o['id'] for o in pending['offers']] == ['softened_heart']
    assert 'pending_roll' not in cold().journey_state(jid, B)['actors'][A]
    options = cold().journey_menu(jid, A)['options']
    assert {o['kind'] for o in options} == {'roll_decide'} and len(options) == 2
    with pytest.raises(ValueError, match='Decide your open roll'):
        act('wait', {'seconds': 1})
    assert not events(cold, jid, 'CHECK_RESOLVED')
    result = act('roll_decide', {'offer': 'softened_heart'})
    state = cold().journeys.load(jid).state
    added = events(cold, jid, 'ROLL_BONUS_ADDED')[0]
    resolved = events(cold, jid, 'CHECK_RESOLVED')[0]
    rolled = events(cold, jid, 'CHECK_ROLLED')[0]['roll']
    assert 1 <= added['value'] <= 4 and added['sides'] == 4
    assert resolved['total'] == rolled['total'] + added['value'] and resolved['added'] == ['softened_heart']
    assert state['actors'][A]['resources'][QI] == qi - 1 and 'pending_roll' not in state['actors'][A]
    assert cold().journeys.replay(jid)['status'] == 'PASS'


def test_declining_keeps_the_roll_and_the_point(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART])
    task(admit)
    qi = cold().journeys.load(jid).state['actors'][A]['resources'][QI]
    act('roll_check', {'task': 'plea'})
    act('roll_decide', {'offer': ''})
    resolved = events(cold, jid, 'CHECK_RESOLVED')[0]
    assert resolved['total'] == events(cold, jid, 'CHECK_ROLLED')[0]['roll']['total'] and resolved['added'] == []
    assert cold().journeys.load(jid).state['actors'][A]['resources'][QI] == qi
    assert events(cold, jid, 'ROLL_BONUS_DECLINED') and cold().journeys.replay(jid)['status'] == 'PASS'
    with pytest.raises(ValueError, match='open roll'):
        act('roll_decide', {'offer': ''})


def test_an_unknown_dc_stays_hidden_and_an_unnamed_check_is_not_offered(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART])
    task(admit, 'hidden', known=False)
    assert act('roll_check', {'task': 'hidden'})['actors'][A]['pending_roll']['dc'] is None
    act('roll_decide', {'offer': ''})
    task(admit, 'bargain', tags=('price',))
    act('roll_check', {'task': 'bargain'})  # nothing to add: it resolves at once, nobody is asked
    assert 'pending_roll' not in cold().journeys.load(jid).state['actors'][A]
    task(admit, 'strength', ability='STR')
    act('roll_check', {'task': 'strength'})
    assert [e['task_id'] for e in events(cold, jid, 'CHECK_RESOLVED')] == ['hidden', 'bargain', 'strength']


def test_an_automatic_seat_adds_only_to_a_failure_it_can_see_and_can_still_fix(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART], automatic=True)
    task(admit, 'seen', dc=1000)           # a failure it can see, but no d4 could reach it
    task(admit, 'unseen', dc=1000, known=False)
    task(admit, 'fixable', dc=1, known=True)  # already passes: nothing to fix
    for name in ('seen', 'unseen', 'fixable'):
        act('roll_check', {'task': name})
    assert not events(cold, jid, 'ROLL_BONUS_ADDED')
    assert 'pending_roll' not in cold().journeys.load(jid).state['actors'][A]
    assert cold().journeys.replay(jid)['status'] == 'PASS'


def test_a_merit_die_is_a_pool_die_added_once_per_roll(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, spheres=['tianxia.sphere.sect_stewardship'])
    task(admit, 'petition', tags=('sect_check',), ability='CHA')
    held = cold().journeys.load(jid).state['actors'][A]['resources'][MERIT]
    pending = act('roll_check', {'task': 'petition'})['actors'][A]['pending_roll']
    assert [o['id'] for o in pending['offers']] == ['merit_die'] and pending['offers'][0]['sides'] == 4
    act('roll_decide', {'offer': 'merit_die'})
    assert cold().journeys.load(jid).state['actors'][A]['resources'][MERIT] == held - 1
    assert len(events(cold, jid, 'ROLL_BONUS_ADDED')) == 1 and 'pending_roll' not in cold().journeys.load(jid).state['actors'][A]
    assert cold().journeys.replay(jid)['status'] == 'PASS'


def test_a_check_task_needs_a_feature_that_adds_and_is_typed(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART])
    with pytest.raises(ValueError, match='typed check'):
        admit('check_task', {'id': 'x', 'description': 'Luck check', 'ability': 'LUCK', 'dc': 5, 'dc_known': True, 'tags': [], 'proficient': False})
    with pytest.raises(ValueError, match='no feature'):
        cold().journey_admit(jid, cold().journey_state(jid)['revision'], B, 'check_task',
                             {'id': 'x', 'description': 'Plea', 'ability': 'CHA', 'dc': 5, 'dc_known': True, 'tags': [], 'proficient': False}, gm=True, reason='x y')


def test_the_softened_heart_rider_is_gone_and_the_record_still_names_its_cost():
    record = json.loads((ROOT / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics'][HEART]
    assert record['riders'] == [] and any(e['type'] == 'spend_resource' and e['flat'] == 1 for e in record['effects'])


def test_a_hidden_check_keeps_its_dc_and_its_result_to_its_own_seat(tmp_path, monkeypatch):
    # A check whose DC the roller does not know is that seat's business, not the table's.
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART])
    task(admit, 'hidden', dc=17, known=False)
    act('roll_check', {'task': 'hidden'})
    act('roll_decide', {'offer': ''})
    other = cold().journey_state(jid, B)
    public = cold().journey_state(jid)
    mine = cold().journey_state(jid, A)
    # another seat learns neither the DC nor the roll nor the outcome
    assert other['actors'][A]['check_tasks']['hidden']['dc'] is None
    assert '"dc": 17' not in json.dumps(other)
    assert [e['kind'] for e in other['events']
            if e['kind'] in ('CHECK_ROLLED', 'CHECK_RESOLVED', 'ROLL_BONUS_ADDED')] == []
    # and neither does the projection without a viewer
    assert public['actors'][A]['check_tasks']['hidden']['dc'] is None
    assert [e['kind'] for e in public['events']
            if e['kind'] in ('CHECK_ROLLED', 'CHECK_RESOLVED')] == []
    # the owner still sees their own roll and its outcome, without the DC they do not know
    assert [e['kind'] for e in mine['events']
            if e['kind'] in ('CHECK_ROLLED', 'CHECK_RESOLVED')] == ['CHECK_ROLLED', 'CHECK_RESOLVED']
    assert mine['actors'][A]['check_tasks']['hidden']['dc'] is None
    # the saved journey keeps its own record; only the projection is redacted
    assert [e['kind'] for e in cold().journeys.load(jid).state['events']
            if e['kind'] == 'CHECK_RESOLVED'] == ['CHECK_RESOLVED']


def test_a_check_with_a_known_dc_stays_open_to_the_table(tmp_path, monkeypatch):
    # Only a hidden DC is private: a known DC and its result are the table's business.
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART])
    task(admit, 'open', dc=12, known=True)
    act('roll_check', {'task': 'open'})
    act('roll_decide', {'offer': ''})
    other = cold().journey_state(jid, B)
    assert other['actors'][A]['check_tasks']['open']['dc'] == 12
    assert 'CHECK_RESOLVED' in [e['kind'] for e in other['events']]


def test_a_merit_die_keeps_its_printed_size_however_the_pool_is_stored(tmp_path, monkeypatch):
    # The Merit Die is a d4 that grows to a d10 at most, whatever the stored pool says.
    cold, jid, act, admit = game(tmp_path, monkeypatch, spheres=['tianxia.sphere.sect_stewardship'])
    store = cold().journeys.root / 'State.json'
    for stored, expected in ((0, 4), (99, 10)):
        registry = json.loads(store.read_text())
        registry['sessions'][jid]['actors'][A]['resources'][MERIT_SIZE] = stored
        store.write_text(json.dumps(registry))
        name = f'petition{stored}'
        task(admit, name, tags=('sect_check',), ability='CHA')
        pending = act('roll_check', {'task': name})['actors'][A]['pending_roll']
        assert [o['id'] for o in pending['offers']] == ['merit_die']
        assert pending['offers'][0]['sides'] == expected
        act('roll_decide', {'offer': ''})


def test_the_scenario_owner_can_close_an_open_roll(tmp_path, monkeypatch):
    # A manual owner who never answers must not lock that creature out of its journey.
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART])
    task(admit, 'plea')
    act('roll_check', {'task': 'plea'})
    with pytest.raises(ValueError, match='Decide your open roll'):
        act('wait', {'seconds': 1})
    admit('cancel_check', {})
    state = cold().journeys.load(jid).state
    assert 'pending_roll' not in state['actors'][A]
    assert events(cold, jid, 'ROLL_WINDOW_CANCELLED')
    assert events(cold, jid, 'CHECK_RESOLVED')
    act('wait', {'seconds': 1})  # the creature travels on
