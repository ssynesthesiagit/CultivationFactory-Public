"""Unmodified production Active Defense reading, separate from synthetic input.

This deliberately does not install the synthetic trigger/authority fixture.
It must exercise the production classifier, including any production overlay.
"""
import json

import pytest

from combat import factory_compiler, reaction_triggers
from tests.active_defense_table_support import A, acquired_combat
from tests.active_defense_authority_support import TRIGGER


def test_actual_production_trigger_survives_acquisition_and_compilation(tmp_path, monkeypatch):
    original_authority = factory_compiler.TYPED_AUTHORITY
    original_readings = reaction_triggers.READINGS_PATH
    mechanic = json.loads(original_authority.read_text())['mechanics']['SHIELD_BASE_ACTIVE_DEFENSE']
    if (mechanic.get('activation') or {}).get('trigger') != TRIGGER:
        # Public exports replace printed prose (see active_defense_authority_support). This check reads the printed
        # trigger, so it runs only where the printed authority is present; the synthetic tests cover the public path.
        pytest.skip('authority carries different Active Defense prose (public export)')
    matches = reaction_triggers.classify_mechanic_all(mechanic)
    assert any(match.kind == 'attacked' for match in matches), matches
    table, mid = acquired_combat(tmp_path, monkeypatch, synthetic=False)
    assert factory_compiler.TYPED_AUTHORITY == original_authority
    assert reaction_triggers.READINGS_PATH == original_readings
    engine = table.combat._load_session(mid).engine
    rows = [r for r in engine.typed_reaction_rows[A] if r.get('feature_id') == 'SHIELD_BASE_ACTIVE_DEFENSE']
    assert len(rows) == 1 and rows[0]['after_attack_roll'], rows
    assert rows[0]['effects'][0]['duration'] == 'triggering_attack'
