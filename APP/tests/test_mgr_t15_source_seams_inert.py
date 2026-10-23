"""Finding 3 regression (MGR-T15 Oath-Skin Frame F12R): the source-event seams are inert.

The four campaign source-event hooks in combat/ext/__init__.py are default-inert:
an event or receipt for any other source must produce no provider answer, no event,
no state change and an identical sheet. Providers that do claim Oath-Skin Frame are
covered by the Oath-Skin Frame files. These checks pass no engine: an inert provider
returns before it touches one.
"""
from combat import ext
from combat.source_events import SourceEvent

OTHER = 'foundation.iron_oath_skin_v0_2B.some_other_feature'
HASH = 'a' * 64


def _event(source_id=OTHER, kind='available'):
    return SourceEvent(event_id='e1', actor_id='actor-a', source_id=source_id,
                       acquisition_id='acq-1', kind=kind, evidence_sha256=HASH, data={})


def test_validate_source_event_has_no_answer_for_unrelated_source():
    assert ext.run_strict('validate_source_event', None, _event()) == []


def test_validate_source_evidence_has_no_answer_for_unrelated_source():
    evidence = {'source_reference': 'x', 'story_effect': 'y', 'stabilizations': []}
    assert ext.run_strict('validate_source_evidence', None, _event(), evidence) == []


def test_apply_source_event_is_a_no_op_for_unrelated_source():
    class NoEngine:
        def __getattr__(self, name):
            raise AssertionError('inert provider touched the engine: ' + name)
    assert ext.run_strict('apply_source_event', NoEngine(), _event()) == []


def test_character_source_event_returns_the_same_sheet_for_unrelated_receipt():
    sheet = {'foundation': {'record_id': 'other', 'acquisition_event_id': 'acq-1'}, 'identity': {'x': 1}}
    receipt = {'event': {'source_id': OTHER, 'acquisition_id': 'acq-1'},
               'journal_sha256': HASH, 'sequence': 1}
    assert ext.transform('character_source_event', sheet, receipt) is sheet


def test_character_source_event_ignores_frame_receipt_without_foundation():
    from combat.ext.oath_skin_frame import FRAME
    sheet = {'identity': {'x': 1}}
    receipt = {'event': {'source_id': FRAME, 'acquisition_id': 'acq-1'},
               'journal_sha256': HASH, 'sequence': 1}
    assert ext.transform('character_source_event', sheet, receipt) is sheet
