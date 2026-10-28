"""Sol RB2 review regressions for the Abyssal Pressure Seal lane.

B1: the reviewed authority record must carry the printed trigger, the printed
    action/CP rider and the printed Water-check rider, with prior attribution kept.
B2: the lane must not re-pin proof dependencies it does not change; the two pin tables
    must agree on shared dependencies.
O1: the seal's travel-classification comment sits before the loop it documents.
O2: the owned-hook contract note in combat/ext/__init__.py names one hook per line.

Pure data/source checks: no engine, no model server.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from tools import automation_truth_effects
from tools import automation_truth_plugin_proofs

ROOT = Path(__file__).resolve().parents[1]
SEAL = 'TAL_WATER_ABYSSAL_PRESSURE_SEAL'
EXPIRY = ROOT / 'authority/typed_mechanics/reviewed_final.d/expiry_fixes.json'
RULES = ROOT / 'authority/typed_mechanics/rules_text.json'
PRINTED_TRIGGER = ('When a creature is Restrained by Whirlpool Prison, affected by Drowning Pressure, '
                   'or inside your Court of the Endless Tide')
PRINTED_RIDERS = (
    'you may use an action and spend 4 CP to seal it in abyssal pressure',
    'if it attempts to teleport, fly, or move through a planar or spatial technique, '
    'it must first succeed on a Water check contested by your Cultivation Save DC',
)


def _record():
    return json.loads(EXPIRY.read_text())['mechanics'][SEAL]


# --- B1: the authority record restores the printed qualifier and riders -------------

def test_b1_seal_record_restores_printed_trigger():
    assert _record()['activation']['trigger'] == PRINTED_TRIGGER


def test_b1_seal_record_restores_printed_riders():
    assert _record()['riders'] == list(PRINTED_RIDERS)


def test_b1_printed_text_still_carries_the_same_qualifier_and_riders():
    # The record must mirror the printed text, not a paraphrase of it.
    printed = json.loads(RULES.read_text())[SEAL]
    assert f'{PRINTED_TRIGGER}, {PRINTED_RIDERS[0]}.' in printed
    assert f'{PRINTED_RIDERS[1]}.' in printed


def test_b1_prior_reviewer_attribution_is_kept_with_new_one():
    reviewed_by = _record()['reviewed_by']
    assert reviewed_by.startswith('riders-lane1 Codex 2026-09-29')
    assert 'MGR-T15' in reviewed_by


def test_b1_structured_cp_cost_is_the_only_payment_source():
    # The 4 CP is paid once, through the pre-payment cost; no duplicate spend effect.
    record = _record()
    spends = [e for e in record['effects'] if e.get('type') == 'spend_resource']
    assert spends == []
    assert record['cost'] == [[{'resource': 'cp', 'amount': 4, 'amount_formula': None}]]


# --- B2: the lane must not re-pin files it does not change ----------------------------

UNTOUCHED = ('APP/combat/area_recipients.py', 'APP/combat/area_recipient_rules.py')
MAIN_PINS = {
    'APP/combat/area_recipients.py': '6b74c903e8d3df602065eadbec4f1242cb4ccd2abddce78bc63cb8d6eccc188a',
    'APP/combat/area_recipient_rules.py': 'a4ab221f85ba5d6e996141799702db386c5f5103e45c279d3a6be3e9f37493e6',
}


CHANGED_DEPENDENCIES = ('APP/combat/typed_executor.py', 'APP/combat/ext/__init__.py')


def _current_digest(relative):
    # ROOT is APP/; the dependency paths above are relative to the repository root.
    return hashlib.sha256((ROOT.parent / relative).read_bytes()).hexdigest()


def test_b2_untouched_dependency_pins_keep_main_values():
    for table in (automation_truth_effects._REVIEWED_SHA256,
                  automation_truth_plugin_proofs._REVIEWED_SHA256):
        for relative in UNTOUCHED:
            assert table[relative] == MAIN_PINS[relative], relative


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
