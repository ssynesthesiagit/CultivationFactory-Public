"""Focused merge guard: native tool receipts and relocated-item catch inputs.

Reuse the service/cold-replay regressions that failed in the neighboring run.
The explicit registry paths preserve their dynamic native inputs in public CI.
"""
import json
from pathlib import Path

import pytest

from combat.gate2_engine import Gate2Engine
from tests.test_mgr_t13_blacksmith_identity_review import native_registry_input  # noqa: F401
from tests.test_mgr_t13_blacksmith_carriers import (
    test_exact_native_tool_check as _tool_case,
    test_tool_prompt_names_initiator_and_checked_creature as _prompt_case,
)
from tests.test_mgr_t13_blacksmith_review import (
    test_native_relocated_mark_survives_original_owner_and_reload as _relocation_case,
    TRAITOR,
)


@pytest.fixture(autouse=True)
def native_catch_registry_input():
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root / 'combat/rules/feature_blocks.d/riders_lane10.json').read_text())
    assert rows['features'][TRAITOR]['kind'] == 'traitorous_blade'


@pytest.mark.parametrize('used', [None, {'owner': 'original-owner', 'key': 'tool'}])
def test_check_context_keeps_optional_tool_and_main_hazards(used):
    # This projection needs only an active native frame, no fight or dice. The
    # service cases below prove that actual tool rolls publish and consume it.
    engine = Gate2Engine.__new__(Gate2Engine)
    frame = {'kind': 'check', 'actor_id': 'bearer', 'source_id': 'check:tool',
             'ability': 'INT', 'hazards': ['heat']}
    if used is not None:
        frame['used_tool'] = dict(used)
    engine._d20_scopes = (frame,)
    context = engine.d20_context()
    assert context['hazards'] == ['heat']
    if used is None:
        assert 'used_tool' not in context
    else:
        assert context['used_tool'] == used
        context['used_tool']['key'] = 'changed copy'
        assert frame['used_tool'] == used
    context['hazards'].append('cold')
    assert frame['hazards'] == ['heat']


@pytest.mark.parametrize('name,use', [
    ('Tool check', True), ('Tool check', False),
    ('Unbound check', True), ('Wrong tool check', True),
])
def test_native_tool_receipt_after_main_merge(tmp_path, name, use):
    _tool_case(tmp_path, name, use)


def test_native_tool_prompt_after_main_merge(tmp_path):
    _prompt_case(tmp_path)


@pytest.mark.parametrize('defeated', [False, True])
def test_native_catch_has_real_ownership_input(tmp_path, monkeypatch, defeated):
    _relocation_case(tmp_path, monkeypatch, 'catch', defeated)
