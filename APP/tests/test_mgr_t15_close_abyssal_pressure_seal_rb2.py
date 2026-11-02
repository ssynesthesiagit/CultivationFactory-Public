"""Sol RB2 review regressions for the Abyssal Pressure Seal lane.

B1: the reviewed authority record must carry the printed trigger, the printed
    action/CP rider and the printed Water-check rider, with prior attribution kept.
B2: the lane must not re-pin proof dependencies it does not change; the two pin tables
    must agree on shared dependencies.
O1: the seal's travel-classification comment sits before the loop it documents.
O2: the owned-hook contract note in combat/ext/__init__.py names one hook per line.

Pure data/source checks: no engine, no model server. This test imports only standard-library modules,
so public CI can run the complete assertions against the corpus shipped in its checkout.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import tokenize
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


def _source_digest(source: bytes) -> str:
    """Match the public pin format without importing private automation tooling."""
    text = source.decode('utf-8')
    docstrings = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add((first.lineno, first.col_offset))
    ignored = {tokenize.COMMENT, tokenize.NL, tokenize.ENCODING}
    out, after_doc = [], False
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in ignored:
            continue
        if token.type == tokenize.STRING and token.start in docstrings:
            after_doc = True
            continue
        if after_doc and token.type == tokenize.NEWLINE:
            after_doc = False
            continue
        after_doc = False
        out.append(f'{tokenize.tok_name[token.type]}:{token.string}')
    return hashlib.sha256('\n'.join(out).encode()).hexdigest()


def _pin_table(path):
    module = ast.parse(path.read_text())
    assign = next(node for node in module.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == '_REVIEWED_SHA256'
                          for target in node.targets))
    return ast.literal_eval(assign.value)


# --- B1: the authority record restores the printed qualifier and riders -------------

def test_b1_seal_record_restores_printed_trigger():
    # Compare the complete sentence, including words and punctuation, not a partial token pattern.
    trigger = _record()['activation']['trigger']
    assert trigger
    assert any(line == f'{trigger},' or line.startswith(f'{trigger}, ') for line in _clause_lines())


def test_b1_seal_record_restores_printed_riders():
    record = _record()
    assert len(record['riders']) == 2
    lines = _clause_lines()
    trigger, action_rider = record['activation']['trigger'], record['riders'][0]
    water_rider = record['riders'][1]
    assert any(line == f'{trigger}, {action_rider}.' for line in lines)
    assert any(line == f'{water_rider}.' for line in lines)


def test_b1_printed_text_still_carries_the_same_qualifier_and_riders():
    # The record must mirror the printed sentence, not a paraphrase of it: the printed text carries the record's
    # trigger and its action/CP rider as one clause ("<trigger>, <rider>.") and the Water-check rider after it.
    lines = _clause_lines()
    trigger = _record()['activation']['trigger']
    action_rider, water_rider = _record()['riders']
    action_line = f'{trigger}, {action_rider}.'
    water_line = f'{water_rider}.'
    assert action_line in lines
    assert water_line in lines
    assert lines.index(water_line) > lines.index(action_line)


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
    path = ROOT.parent / relative
    return _source_digest(path.read_bytes())


def test_b2_changed_dependency_pins_match_current_source():
    # The lane edits these two files, so both proof tables must pin the bytes shipped now.
    for table_path in (ROOT / 'tools/automation_truth_effects.py',
                       ROOT / 'tools/automation_truth_plugin_proofs.py'):
        table = _pin_table(table_path)
        for relative in CHANGED_DEPENDENCIES:
            assert table[relative] == _current_digest(relative), relative


def test_b2_pin_tables_agree_on_shared_dependencies():
    effects = _pin_table(ROOT / 'tools/automation_truth_effects.py')
    proofs = _pin_table(ROOT / 'tools/automation_truth_plugin_proofs.py')
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
