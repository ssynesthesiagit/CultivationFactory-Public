"""Regressions for review finding 2: comparison flags and note match receipt bytes.

Finding 2 was a documentation defect, not a gameplay defect. ``compare_receipts.py``
recomputes every flag from the raw receipts on disk, and all nine base/head pairs are
byte-identical -- but the ``note`` it wrote into ``historical-comparison.json`` said
"Raw equality ... is not attainable and is not claimed", and explained the difference by
claiming the engine binding had changed. Both claims contradicted the artifact's own
flags (``all_raw_identical: true``, ``cases_with_engine_binding_difference: []``) and its
own recomputed bytes. A future reviewer reading that note would conclude the observed
equality was impossible, i.e. that the artifact was wrong.

The same class of defect is the one that produced round 1's finding 1, where a label
outran its artifact, so this regression pins the general rule rather than the wording:
**the note may never assert the opposite of what the recomputed flags show.** It exercises
the evidence artifact directly; no gameplay behavior is behind a JSON string. The separate
continuation identity regression covers
``test_historical_evidence_contract.py`` (session intent into ``execute_intent`` plus a cold
reload), covered by earlier lane evidence.

Point it at any comparison artifact; the before/after proof uses the pre-fix note saved as
historical-comparison.before.json and the regenerated one.
"""
import json
import os
from pathlib import Path

import pytest

DEFAULT = Path('/var/tmp/auto-audit/fix/A2BERSERKEr7-evidence/historical-comparison.json')
TARGET = Path(os.environ.get('A2BERSERKEr_COMPARISON', DEFAULT))
RECEIPTS = Path(os.environ.get('A2BERSERKEr_RECEIPTS', str(TARGET.parent)))
# The comparison artifact is lane evidence, not a shipped file. The controlled fixture
# below remains runnable when that external evidence is absent.
requires_comparison = pytest.mark.skipif(not TARGET.is_file(), reason=f'lane comparison artifact absent: {TARGET}')

# Phrases that deny an equality the artifact's own flags report.
DENIALS = ('not attainable', 'is not claimed', 'cannot be equal', 'is not equal')


def comparison():
    assert TARGET.is_file(), f'comparison artifact is missing: {TARGET}'
    meta = json.loads(TARGET.read_text())
    assert 'cases' in meta and meta['cases'], 'artifact declares no cases, so it proves nothing'
    return meta


def validate_receipt_flags(meta, receipt_root):
    """Recompute per-case equality from the raw and normalized files on disk."""
    for case in meta['cases']:
        name = case['name']
        for suffix, flag in [('', 'raw_identical'), ('.normalized', 'normalized_identical')]:
            left = receipt_root / 'historical-base' / f'{name}{suffix}.json'
            right = receipt_root / 'historical-head' / f'{name}{suffix}.json'
            assert left.is_file() and right.is_file(), f'missing {flag} receipt pair: {left}, {right}'
            assert case[flag] == (left.read_bytes() == right.read_bytes()), (
                f'{name} {flag} does not match the receipt bytes')
    assert meta['all_raw_identical'] == all(c['raw_identical'] for c in meta['cases'])
    assert meta['all_normalized_identical'] == all(c['normalized_identical'] for c in meta['cases'])
    assert meta['cases_with_raw_difference'] == [c['name'] for c in meta['cases'] if not c['raw_identical']]


@requires_comparison
def test_each_case_flag_matches_the_receipt_bytes():
    meta = comparison()
    validate_receipt_flags(meta, RECEIPTS)


@requires_comparison
def test_the_note_does_not_deny_the_equality_the_flags_report():
    """The pre-fix defect: flags said equal, note said equality was unattainable."""
    meta = comparison()
    note = meta.get('note', '').lower()
    if meta['all_raw_identical']:
        for phrase in DENIALS:
            assert phrase not in note, (
                'the note denies raw equality while all_raw_identical is true, so the artifact '
                f'states its own result is impossible: {meta["note"]!r}')


# A note must positively affirm equality when the artifact records no difference. Phrase
# denial is deliberately not used here: a correct note may still describe the general
# mechanism ("an engine binding change would normally mint a different continuation id"),
# so what matters is that it says what happened in *this* comparison.
NO_CHANGE_AFFIRMED = ('base_engine_binding_sha256 equals head_engine_binding_sha256',
                      'no such change occurs', 'binding does not cover')


@requires_comparison
def test_the_note_does_not_blame_a_binding_change_that_did_not_happen():
    """The pre-fix note explained the result by a change the artifact never recorded."""
    meta = comparison()
    note = meta.get('note', '').lower()
    if not meta.get('cases_with_engine_binding_difference'):
        assert any(phrase in note for phrase in NO_CHANGE_AFFIRMED), (
            'no case shows an engine-binding difference, so the note must say the binding did '
            'not change; instead it leaves a binding change as the explanation the artifact '
            f'contradicts: {meta["note"]!r}')


@requires_comparison
def test_a_note_is_present_and_names_the_reason_it_is_checkable():
    meta = comparison()
    note = meta.get('note', '')
    assert note.strip(), 'the artifact carries no note at all'
    # Whatever the outcome, the note must point at the field a reviewer can re-check.
    assert 'engine' in note.lower(), (
        f'the note does not say what the reader should check: {note!r}')


@pytest.mark.parametrize('flag_name', ['raw_identical', 'normalized_identical'])
def test_opposite_case_flag_is_rejected(flag_name, tmp_path):
    """A fixture with consistently false bytes/flags passes; flipping its flag fails."""
    base, head = tmp_path / 'historical-base', tmp_path / 'historical-head'
    base.mkdir(); head.mkdir()
    (base / 'fixture.json').write_bytes(b'base')
    (head / 'fixture.json').write_bytes(b'head')
    (base / 'fixture.normalized.json').write_bytes(b'same')
    (head / 'fixture.normalized.json').write_bytes(b'same')
    meta = {'cases': [{'name': 'fixture', 'raw_identical': False, 'normalized_identical': True}],
            'all_raw_identical': False, 'all_normalized_identical': True,
            'cases_with_raw_difference': ['fixture']}
    validate_receipt_flags(meta, tmp_path)
    meta['cases'][0][flag_name] = not meta['cases'][0][flag_name]
    with pytest.raises(AssertionError, match='does not match the receipt bytes'):
        validate_receipt_flags(meta, tmp_path)
