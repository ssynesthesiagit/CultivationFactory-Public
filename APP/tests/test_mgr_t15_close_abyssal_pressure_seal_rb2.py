"""Sol RB2 review regressions for the Abyssal Pressure Seal lane (public copy).

B1 (public part): the reviewed authority record keeps the printed trigger and riders in the
    printed shape (token count, order, token length, capitalisation, digits), and keeps its
    prior attribution. The public export scrambles prose per token but keeps those shape
    markers, so these checks run on the public copy. The word-exact comparison lives in
    tests/test_mgr_t15_close_abyssal_pressure_seal_rb2_clauses.py and stays private.
B2: tests/test_automation_truth_pins_current.py checks every pin in both tables against the
    checked-in source, so the two tables cannot disagree on a shared dependency. This file
    does not repeat that check.
O1: the seal's travel-classification comment sits before the loop it documents.
O2: the owned-hook contract note in combat/ext/__init__.py names one hook per line.

Pure data/source checks: no engine, no model server. Standard-library imports only.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEAL = 'TAL_WATER_ABYSSAL_PRESSURE_SEAL'
EXPIRY = ROOT / 'authority/typed_mechanics/reviewed_final.d/expiry_fixes.json'
RULES = ROOT / 'authority/typed_mechanics/rules_text.json'
# The prior reviewer's round marker in reviewed_by, as its shape: 12 characters, lowercase opening, one digit.
PRIOR_REVIEWER_SHAPE = (12, '', '1')
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")


def _record():
    return json.loads(EXPIRY.read_text())['mechanics'][SEAL]


def _printed():
    return json.loads(RULES.read_text())[SEAL]


def _shape(text):
    return tuple((len(token), token[0] if token[0].isupper() else '', ''.join(c for c in token if c.isdigit()))
                 for token in TOKEN.findall(text))


def _clause_lines():
    """Return complete printed sentence lines, retaining punctuation and all words."""
    return [line.strip() for line in _printed().splitlines() if line.strip()]


def _shaped_line_indexes(text):
    shape = _shape(text)
    return [i for i, line in enumerate(_clause_lines()) if _shape(line) == shape]


# --- B1: the authority record keeps the printed clause shape and attribution -----------

def test_b1_seal_record_keeps_printed_trigger_and_action_rider_shape():
    record = _record()
    trigger, action_rider = record['activation']['trigger'], record['riders'][0]
    assert len(record['riders']) == 2
    assert _shaped_line_indexes(f'{trigger}, {action_rider}.')


def test_b1_seal_record_keeps_printed_water_rider_shape_after_the_action_clause():
    record = _record()
    trigger, action_rider, water_rider = record['activation']['trigger'], record['riders'][0], record['riders'][1]
    action_index = _shaped_line_indexes(f'{trigger}, {action_rider}.')
    water_index = _shaped_line_indexes(f'{water_rider}.')
    assert action_index and water_index
    assert water_index[0] > action_index[0]


def test_b1_prior_reviewer_attribution_is_kept_with_new_one():
    reviewed_by = _record()['reviewed_by']
    # The attribution itself is prose (so scrambled in the public copy); its markers keep their digits and the prior
    # reviewer's opening marker keeps its shape.
    assert _shape(reviewed_by)[:1] == (PRIOR_REVIEWER_SHAPE,)
    assert '2026-09-29' in reviewed_by
    assert 'MGR-T15' in reviewed_by


def test_b1_structured_cp_cost_is_the_only_payment_source():
    # The 4 CP is paid once, through the pre-payment cost; no duplicate spend effect.
    record = _record()
    spends = [e for e in record['effects'] if e.get('type') == 'spend_resource']
    assert spends == []
    assert record['cost'] == [[{'resource': 'cp', 'amount': 4, 'amount_formula': None}]]


# --- O1: the travel-classification comment documents the loop, not the code after it --

def _function_source(name):
    path = ROOT / 'combat/ext/water_second_pass.py'
    source = path.read_text()
    module = ast.parse(source)
    node = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return source.splitlines()[node.lineno - 1:node.end_lineno]


def test_o1_travel_comment_is_before_the_loop_not_after_the_return():
    lines = _function_source('seal_travel_effects')
    loop = next(i for i, line in enumerate(lines) if line.strip().startswith('for row in rows'))
    returns = [i for i, line in enumerate(lines) if line.strip() == 'return False']
    assert returns and returns[-1] > loop
    after_return = [line for line in lines[returns[-1] + 1:] if line.strip().startswith('#')]
    assert after_return == []
    assert any('not classified here' in line for line in lines[:loop])


# --- O2: the __init__ contract note lists one owned hook per line -----------------

def test_o2_contract_note_names_each_hook_on_its_own_line():
    text = (ROOT / 'combat/ext/__init__.py').read_text().splitlines()
    start = next(i for i, line in enumerate(text) if line.startswith('# Abyssal Pressure Seal (water_second_pass)'))
    end = next(i for i in range(start, len(text)) if 'No seal is default-inert' in text[i])
    block = text[start:end + 1]
    for hook in ('target_eligibility', 'technique_declared', 'movement_attempt',
                 'effect_allowed', 'teleport_context_check'):
        assert any(line.startswith(f'#   {hook}:') for line in block), hook
    assert all(len(line) <= 100 for line in block)
