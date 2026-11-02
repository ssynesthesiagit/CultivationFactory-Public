"""Reviewed ability ports must coexist with the canonical rider authority."""
import json
from pathlib import Path

import pytest


def test_mercy_before_marrow_with_marrow_imported_first(tmp_path):
    """Import order cannot spend a rescue before an accepted nonlethal strike.

    Run the real table commit/reload regression with Marrow registered before
    automatic plug-in discovery, as another plug-in or test consumer may do.
    """
    import os
    import subprocess
    import sys

    result = subprocess.run([
        sys.executable, '-B', '-c',
        'from combat.ext import riders_metal; import pytest; '
        'raise SystemExit(pytest.main(__import__("sys").argv[1:]))',
        '-p', 'no:cacheprovider', '--basetemp=' + str(tmp_path / 'marrow-first'),
        '-q', '--tb=short',
        'tests/test_lock7_merciful.py::test_accepted_mercy_prevents_redundant_iron_marrow_save',
        'tests/test_lock7_merciful.py::test_accepted_mercy_does_not_suppress_followup_rider_marrow_save',
    ], cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_saved_crown_is_defensive_radiance_but_unknown_and_structural_states_are_not():
    from types import SimpleNamespace
    from combat.ext.end_effect import helpful

    def held(name, data=None):
        return SimpleNamespace(condition_id='condition:typed.' + name, data=data or {})

    # Old Crowns have no embedded rule; the named printed defense must still qualify.
    assert helpful(held('crown_of_borrowed_light'), 'condition', defensive_only=True)
    assert not helpful(held('unknown_test_state'), 'condition')
    assert not helpful(held('mounted', {'rule': {'effect_kind': 'benefit'}}), 'condition')


def test_edited_text_review_accepts_absent_optional_delivery_but_requires_core_and_exact_hash():
    from tools.typed_mechanics_helpers import _FINAL_FIELDS, _typed_for_text
    final = {field: None for field in _FINAL_FIELDS if field != 'weapon_delivery'}
    final['text_sha256'] = 'reviewed-text'
    assert _typed_for_text('reviewed', 'reviewed-text', {'reviewed': final})
    assert not _typed_for_text('reviewed', 'other-text', {'reviewed': final})
    incomplete = {key: value for key, value in final.items() if key != 'cost'}
    assert not _typed_for_text('reviewed', 'reviewed-text', {'reviewed': incomplete})


def test_spatial_edge_keeps_owner_printed_path_modifier_with_one_override():
    authority = Path(__file__).resolve().parents[1] / 'authority'
    mechanic_id = 'TAL_SPACE_SPATIAL_EDGE'
    rows = [data['mechanics'][mechanic_id]
            for path in (authority / 'typed_mechanics/reviewed_final.d').glob('*.json')
            if mechanic_id in (data := json.loads(path.read_text()))['mechanics']]
    assert len(rows) == 1
    assert rows[0]['effects'][0]['on_hit'][0]['formula'] == 'key_ability_modifier'


def test_punishment_has_one_reviewed_override_and_the_printed_low_level_band():
    authority = Path(__file__).resolve().parents[1] / 'authority'
    mechanic_id = 'tianxia.talent.protection.punishment'
    rows = [data['mechanics'][mechanic_id]
            for path in (authority / 'typed_mechanics/reviewed_final.d').glob('*.json')
            if mechanic_id in (data := json.loads(path.read_text()))['mechanics']]
    assert len(rows) == 1
    damage = next(effect for effect in rows[0]['effects'] if effect['type'] == 'damage')
    assert damage['formula'] == 'pb'
    assert damage['dice_by_cl'][0] == [1, 4, 0, 6]


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('primary', ['Qi', 'Stamina'])
@pytest.mark.parametrize('talent,label,price', [
    ('tianxia.talent.gravity.gravitic_armor', 'Gravitic Armor', 5),
    ('tianxia.talent.gravity.orbiting_guard', 'Orbiting Guard', 1),
    ('tianxia.talent.gravity.moon_weight_incarnation', 'Moon-Weight Incarnation', 10),
])
def test_gravity_self_buffs_pay_printed_alternative_and_reload(tmp_path, auto, primary, talent, label, price):
    from tests.hunt28_support import OWNER, fixture, owner_turn, reload, send
    combat, table, mid = fixture(tmp_path, [talent], cp=price, primary=primary)
    def offered():
        return [o for g in table.state(mid)['menu']['actions'] if g['label'].startswith(label) for o in g['options']]
    assert offered(), 'Fresh compilation must encode the printed CP-or-Stamina price'
    assert send(combat, table, mid, offered()[0]['candidate_id'], auto)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[OWNER].resources['resource:core.' + primary.lower()] == 0
    assert any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER and e.payload.get('amount') == price
               for e in engine.events)
    owner_turn(table, mid, next_turn=True)
    assert not offered(), 'No unpaid repeat after consuming the printed price'
