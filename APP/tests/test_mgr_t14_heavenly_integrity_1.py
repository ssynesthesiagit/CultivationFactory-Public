"""Heavenly Integrity: native hostile producers, table commits and cold replay."""
import hashlib
import json
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.gate2_rolls import DeterministicRollAuthority
from tests.test_a2_foundations_two import table_fixture, use, pressure_action
from tests.worker2_support import OWNER, FOE, turn, reload

PREFIX = 'foundation.heavenly_body_v0_2F.'
POOL = 'resource:foundation.heavenly_integrity'
FLAG = 'foundation_round_vessel'


def pressure(bundles):
    pressure_action(bundles, 'con', 'poisoned')
    action = bundles[2]['action_catalog'][-1]
    action['economy'] = 'BONUS_ACTION'
    # Fixed draw 10, exact native actor modifier, six short of success.
    action['parameters']['typed']['numbers']['save_dc'] = 10 + bundles[0]['actor_template']['saving_throws']['CON'] + 6
    bundles[2].pop('bundle_sha256', None)
    bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])


@pytest.mark.parametrize('stage,bonus', [('Awakened', None), ('Refined', None), ('Perfected', 8)])
def test_native_grant_then_rejection_claims_only_perfected_vessel(tmp_path, monkeypatch, stage, bonus):
    monkeypatch.setattr(DeterministicRollAuthority, '_die', lambda self, sides: (min(10, sides), 0))
    combat, table, mid = table_fixture(tmp_path, 'integrity', current=0, stage=stage, transform=pressure)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER)
    banked = reload(tmp_path, mid)
    grants = [e for e in banked.events if e.event_type == 'RESOURCE_GAINED' and e.source_definition_id == 'passive:' + PREFIX + 'generate_heavenly_integrity']
    assert len(grants) == 1
    assert banked.state.actors[OWNER].resources[POOL] == 1
    use(combat, table, mid, 'Hostile pressure', OWNER)
    engine = reload(tmp_path, mid)
    rescues = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == PREFIX + 'integrity_rejection']
    if bonus is None:
        assert not rescues
        assert FLAG not in engine.state.actors[OWNER].turn_flags
        assert engine.state.actors[OWNER].resources[POOL] == 1
    else:
        assert len(rescues) == 1 and rescues[0].payload['bonus'] == bonus
        assert engine.state.actors[OWNER].turn_flags[FLAG] == engine.state.round_number
        assert engine.state.actors[OWNER].resources[POOL] == 0
        assert engine.state.actors[OWNER].reaction_available
        assert grants[0].sequence < rescues[0].sequence


def test_guard_used_vessel_cannot_repeat_bonus_on_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(DeterministicRollAuthority, '_die', lambda self, sides: (min(10, sides), 0))
    # A pre-existing resource boundary complements the real-producer case above.
    combat, table, mid = table_fixture(tmp_path, 'integrity', current=1, transform=pressure)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].turn_flags[FLAG] == engine.state.round_number
    assert engine.state.actors[OWNER].resources[POOL] == 1  # actual residual hostile damage refreshes it
    use(combat, table, mid, 'Hostile pressure', OWNER)
    engine = reload(tmp_path, mid)
    assert not any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == PREFIX + 'integrity_rejection' for e in engine.events)
    assert engine.state.actors[OWNER].resources[POOL] == 1


def test_full_controlling_records_match_decoded_source_hashes():
    source = json.loads((Path(__file__).resolve().parents[1] / 'authority/typed_mechanics/rules_text.json').read_text())
    hashes = {
        'generate_heavenly_integrity': '4cf3bc839cfcdc45c5e90e5bd204ee94b2bc89dc6010977b74bc4505c3d6424b',
        'heaven_recognized_vessel': 'b6b51ac028b5f8fe126c853b453bc3ac02453f62cd13866a16e76c72fbe6f4e0',
        'integrity_guard': '9a2d219feb2c742970c381ab2a0ca34c102bc00f64987c1cf6d8218387de4f99',
    }
    for leaf, expected in hashes.items():
        assert hashlib.sha256(source[PREFIX + leaf].encode()).hexdigest() == expected
