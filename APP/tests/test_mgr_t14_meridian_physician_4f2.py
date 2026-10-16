"""Native regressions for the 4F2 Search, expiry and travel presentation review."""
import json

import pytest

from tests.test_mgr_t14_clinical_native import (
    A, B, game, engine, use, final_native_mechanical_replay,
)
from tests.test_mgr_t14_clinical_consumers import prepare, toxin
from tests.test_mgr_t14_meridian_physician_review_fixes import encounter, resume


def test_delayed_veil_keeps_native_disease_provenance_through_treatment(tmp_path, monkeypatch):
    from tests.test_mgr_t14_clinical_native import test_purify_cures_actual_native_disease_manifestation_without_ending_zone
    test_purify_cures_actual_native_disease_manifestation_without_ending_zone(tmp_path, monkeypatch)


def test_unopposed_check_modes_keep_unrelated_rolls_and_creatures_inert(tmp_path, monkeypatch):
    from combat.typed_executor import check_modes
    cold, table, jid, mid = prepare(tmp_path, monkeypatch, 'Clouded Senses')
    loaded = engine(cold, mid)
    patient = loaded.state.actors[B]
    for ability, skill in [('INT', 'Perception'), ('WIS', 'Medicine'), ('WIS', None)]:
        assert 'DISADVANTAGE' not in check_modes(patient, ability, skill, engine=loaded)
    assert 'DISADVANTAGE' not in check_modes(loaded.state.actors[A], 'WIS', 'Perception', engine=loaded)
    assert toxin(loaded, 'Clouded Senses')  # previews never consume the next check
    assert 'DISADVANTAGE' in check_modes(patient, 'WIS', 'Perception', engine=loaded)
    # The native Search/commit/reload consumer is also tested in clinical_consumers.


def protocol_game(tmp_path, monkeypatch, *, expires=100000):
    # A native poison has no external expiry clock of its own.
    from tests.test_mgr_t14_clinical_native import anatomy, next_round
    from combat.ext.stacking_marks import count
    # Acquire the poison through the normal imported source and its failed save.
    cold, table, jid, command, world = game(tmp_path, monkeypatch, spheres=('poison',))
    anatomy(world)
    mid = encounter(cold, jid)
    for _ in range(10):
        loaded = engine(cold, mid)
        if count(loaded, loaded.state.actors[A], loaded.state.actors[B], 'Dose Mark') >= 2:
            break
        use(cold, table, mid, 'Deliver the Dose')
        next_round(cold, table, mid)
    use(cold, table, mid, 'Ingrain the Toxin: Bitter Breath',
        choose=lambda p, ids: ['Bitter Breath'] if 'Bitter Breath' in ids else ids[:1])
    resume(cold, table, jid, mid)
    value = {'method': 'Medicine', 'ability': 'WIS', 'skill': 'medicine', 'seconds': 6,
             'costs': {'resource:core.qi': 1}, 'operation': 'treat',
             'source_instance': 'rule:POISON_BASE_INGRAIN_THE_TOXIN'}
    state = cold().journey_state(jid)
    payload = {'source': 'clinical_source', 'subject': B, 'kind': 'clinical_protocol',
               'scope': 'short medicine', 'value': value, 'expires_at': state['seconds'] + expires,
               'readers': [A]}
    cold().journey_world_fact(jid, state['revision'], payload)
    return cold, table, jid, command


def test_expired_last_protocol_clock_cannot_revive_after_combat_and_cold_reload(tmp_path, monkeypatch):
    from combat.ext.clinical_procedures import PROTOCOL
    cold, table, jid, command = protocol_game(tmp_path, monkeypatch, expires=6)
    before = cold().journey_state(jid)
    option = next(o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'clinical_treat')
    mid = encounter(cold, jid, rounds=3)
    assert any(c.condition_id == PROTOCOL for c in engine(cold, mid).state.actors[A].conditions.values())
    resumed = resume(cold, table, jid, mid)
    loaded = engine(cold, mid)
    assert not any(c.data.get('external_expiry') for a in loaded.state.actors.values() for c in a.conditions.values())
    assert toxin(loaded, 'Bitter Breath')
    assert resumed['seconds'] >= before['seconds'] + 18
    assert not any(o['kind'] == 'clinical_treat' for o in cold().journey_menu(jid, A)['options'])
    saved = cold().journey_state(jid)
    with pytest.raises(ValueError, match='appropriate table-authored clinical protocol'):
        command(option['kind'], option['payload'])
    assert cold().journey_state(jid) == saved
    assert any(json.loads(c)['data'].get('choice') == 'Bitter Breath'
               for c in saved['actors'][B]['encounter_snapshot']['conditions'].values())


def test_cost_bearing_travel_procedure_uses_readable_resource_name(tmp_path, monkeypatch):
    cold, table, jid, command = protocol_game(tmp_path, monkeypatch)
    option = next(o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'clinical_treat')
    assert '1 Qi' in option['label']
    assert 'resource:' not in option['label']
    assert 'Medicine' in option['label'] and '6 seconds' in option['label']
