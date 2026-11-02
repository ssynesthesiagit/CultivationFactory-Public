"""Sol RB2 review regressions for the Abyssal Pressure Seal lane.

B1: the reviewed authority record must carry the printed trigger, the printed
    action/CP rider and the printed Water-check rider, with prior attribution kept.
B2: the lane must not re-pin proof dependencies it does not change; the two pin tables
    must agree on shared dependencies.
O1: the seal's travel-classification comment sits before the loop it documents.
O2: the owned-hook contract note in combat/ext/__init__.py names one hook per line.

Pure data/source checks: no engine, no model server. The printed rulebook wording is
private prose: the public export ships every rules/catalog sentence scrambled (owner
2026-10-20: only short phrases may publish), so this file quotes none of it and
compares a clause by the shape that survives that scramble (see _shape).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from tools import automation_truth_effects
from tools.automation_truth_digest import dependency_digest
from tools import automation_truth_plugin_proofs

ROOT = Path(__file__).resolve().parents[1]
SEAL = 'TAL_WATER_ABYSSAL_PRESSURE_SEAL'
EXPIRY = ROOT / 'authority/typed_mechanics/reviewed_final.d/expiry_fixes.json'
RULES = ROOT / 'authority/typed_mechanics/rules_text.json'
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")
# The prior reviewer's round marker in reviewed_by, as its shape: 12 characters, lowercase opening, one digit.
PRIOR_REVIEWER_SHAPE = (12, '', '1')


def _record():
    return json.loads(EXPIRY.read_text())['mechanics'][SEAL]


def _printed():
    return json.loads(RULES.read_text())[SEAL]


def _shape(text):
    """The clause shape the public export's prose scramble keeps: word count, each word's length, a capitalised
    word's first letter and every digit. The private rulebook text and its scrambled public copy share it, so a
    check built on it guards the record's wording on both: a dropped, reordered, paraphrased or renumbered clause
    (another CP amount, another save) no longer lines up with the printed clause it claims to carry."""
    return tuple((len(token), token[0] if token[0].isupper() else '', ''.join(c for c in token if c.isdigit()))
                 for token in TOKEN.findall(text))


def _clause_offset(printed_shape, clause):
    """Index where CLAUSE starts inside PRINTED_SHAPE as one whole contiguous clause, or None."""
    shape = _shape(clause)
    for start in range(len(printed_shape) - len(shape) + 1):
        if printed_shape[start:start + len(shape)] == shape:
            return start
    return None


# --- B1: the authority record restores the printed qualifier and riders -------------

def test_b1_seal_record_restores_printed_trigger():
    # The record's activation trigger is one whole printed clause, word for word.
    assert _clause_offset(_shape(_printed()), _record()['activation']['trigger']) is not None


def test_b1_seal_record_restores_printed_riders():
    record = _record()
    assert len(record['riders']) == 2
    printed = _shape(_printed())
    for rider in record['riders']:
        assert _clause_offset(printed, rider) is not None, rider


def test_b1_printed_text_still_carries_the_same_qualifier_and_riders():
    # The record must mirror the printed sentence, not a paraphrase of it: the printed text carries the record's
    # trigger and its action/CP rider as one clause ("<trigger>, <rider>.") and the Water-check rider after it.
    printed = _shape(_printed())
    trigger = _record()['activation']['trigger']
    action_rider, water_rider = _record()['riders']
    start = _clause_offset(printed, f'{trigger}, {action_rider}')
    assert start is not None
    assert _clause_offset(printed, water_rider) > start


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


# --- B2: changed proof dependencies match current source ------------------------------

CHANGED_DEPENDENCIES = ('APP/combat/typed_executor.py', 'APP/combat/ext/__init__.py')


def _current_digest(relative):
    # ROOT is APP/; the dependency paths above are relative to the repository root.
    return dependency_digest(relative, (ROOT.parent / relative).read_bytes())


def test_b2_changed_dependency_pins_match_current_source():
    # The lane edits these two files, so both proof tables must pin the bytes shipped now.
    for table in (automation_truth_effects._REVIEWED_SHA256,
                  automation_truth_plugin_proofs._REVIEWED_SHA256):
        for relative in CHANGED_DEPENDENCIES:
            assert table[relative] == _current_digest(relative), relative


def test_b2_pin_tables_agree_on_shared_dependencies():
    effects = automation_truth_effects._REVIEWED_SHA256
    proofs = automation_truth_plugin_proofs._REVIEWED_SHA256
    for relative in set(effects) & set(proofs):
        assert effects[relative] == proofs[relative], relative


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
