"""Review 5F3: strict continuation and journey rollback at service/disk level."""
import pytest

from combat import ext
from combat.gate2_rolls import DeterministicRollAuthority
from combat.ext.athletics_travel import SOURCE
from combat.ext.life_state import encounter_death_saves, is_deceased, UNCONSCIOUS
from tests.test_mgr_t16_athletics_continuation import party, seed, condition, SPOTS
from tests.test_mgr_t16_athletics_travel import game, activate, A, B


def disk_files(root):
    # Catalog reads append diagnostic timing telemetry even on failed commands.
    # Only gameplay persistence must remain byte-identical.
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*')
            if p.is_file() and not p.name.endswith('.lock') and p.name != 'Performance.ndjson'}


def death_failures(monkeypatch):
    original = DeterministicRollAuthority.d20
    def roll(self, **kwargs):
        result = original(self, **kwargs)
        if kwargs['reason'] == 'SAVE:death':
            return result.model_copy(update={'natural_result': 7, 'total': 7})
        return result
    monkeypatch.setattr(DeterministicRollAuthority, 'd20', roll)


@pytest.mark.parametrize('aid', [A, B])
def test_f1_hp_mismatch_aborts_before_journey_or_match_persistence(tmp_path, monkeypatch, aid):
    cold, jid, _ = party(tmp_path, monkeypatch)
    seed(cold, jid, aid, hp=0, life='DYING')
    session = cold().journeys.load(jid)
    session.state['actors'][aid]['bundle']['actor_template']['maximum_hp'] = 70
    cold().journeys.save(session)
    before = cold().journey_state(jid)
    disk = disk_files(tmp_path)
    with pytest.raises(ValueError, match='maximum HP changed'):
        cold().journey_start_combat(jid, before['revision'], {A: 'team:a', B: 'team:b'}, positions=SPOTS)
    assert cold().journey_state(jid) == before
    assert disk_files(tmp_path) == disk
    assert not list(cold().matches_root.iterdir())


def test_f2_first_initiative_dying_actor_saves_before_any_table_action(tmp_path, monkeypatch):
    death_failures(monkeypatch)
    cold, jid, _ = party(tmp_path, monkeypatch)
    seed(cold, jid, B, hp=0, life='DYING', conditions={
        'unconscious': condition(B, 'unconscious', UNCONSCIOUS)},
        saves={'ok': 1, 'bad': 2}, initiative=1000)
    result = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, positions=SPOTS)
    # No table action has been submitted: constructor and cold replay must both
    # observe the snapshot on turn one, not grant an extra healthy turn.
    first = cold()._load_session(result['match_id']).engine.state
    assert first.initiative_order[0] == B
    assert encounter_death_saves(first.actors[B]) == {'ok': 1, 'bad': 3}
    assert is_deceased(first.actors[B]) and not first.actors[B].active
    assert cold()._load_session(result['match_id']).engine.state.model_dump(mode='json') == first.model_dump(mode='json')


@pytest.mark.parametrize('owned,ordinary', [(False, True), (True, False)])
def test_f3_lethal_exposure_rejects_without_saving_or_losing_legal_options(tmp_path, monkeypatch, owned, ordinary):
    cold, jid, act = game(tmp_path, monkeypatch, owner=owned)
    act('travel_exhaustion', {'levels': 5, 'ordinary': ordinary})
    before = cold().journey_state(jid)
    disk = disk_files(tmp_path)
    with pytest.raises(ValueError, match='Six levels of Exhaustion kill'):
        act('travel_exhaustion', {'levels': 1, 'ordinary': ordinary})
    assert cold().journey_state(jid) == before
    assert disk_files(tmp_path) == disk
    menu = cold().journey_menu(jid, A)
    assert any(o['kind'] == 'move' for o in menu['options'])
    if owned:
        assert any(o['kind'] == 'activate' for o in menu['options'])
        activate(act)
    act('move', {'path': [{'x': 1, 'y': 1}]})
    assert cold().journey_state(jid)['actors'][A]['exhaustion'] == 5


@pytest.mark.parametrize('point,kind,payload', [
    ('journey_elapsed', 'wait', {'seconds': 3601}),
    ('journey_rest', 'long_rest', {}),
    ('journey_state_changed', 'incapacitated', {'value': True}),
    ('journey_command', 'activate', {'source': SOURCE}),
])
def test_f4_provider_failure_rolls_back_all_mutations_and_revision(tmp_path, monkeypatch, point, kind, payload):
    cold, jid, act = game(tmp_path, monkeypatch)
    if kind != 'activate':
        activate(act)
    ext.effects()
    def fail(*args):
        args[0].state['actors'][A]['exhaustion'] = 4
        raise ValueError('test provider failed')
    # Run after the real handler: clock/expiry, rest, lifecycle or payment
    # already mutated the working session and still must never reach disk.
    monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS.get(point, ()), fail])
    before = cold().journey_state(jid)
    disk = disk_files(tmp_path)
    with pytest.raises(ValueError, match='test provider failed'):
        act(kind, payload)
    assert cold().journey_state(jid) == before
    assert disk_files(tmp_path) == disk


def test_f4_combat_lifecycle_failure_creates_no_orphan_match(tmp_path, monkeypatch):
    cold, jid, _ = party(tmp_path, monkeypatch)
    ext.effects()
    def fail(session, aid):
        if session.state['phase'] == 'combat':
            raise ValueError('test combat lifecycle failed')
    monkeypatch.setitem(ext._HOOKS, 'journey_state_changed', [*ext._HOOKS.get('journey_state_changed', ()), fail])
    before = cold().journey_state(jid)
    disk = disk_files(tmp_path)
    with pytest.raises(ValueError, match='test combat lifecycle failed'):
        cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, positions=SPOTS)
    assert cold().journey_state(jid) == before
    assert disk_files(tmp_path) == disk
