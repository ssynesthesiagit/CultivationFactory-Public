"""Compact failures for full replay captures; no pytest diff of huge operands.

Used by stock, cross-revision and save/reload guards. Equality is evaluated on
the original operands, so encoding here affects diagnostics only, never verdicts.
"""
import hashlib
import json
import reprlib


def _encoded(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode('utf-8')
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def assert_replay_equal(left, right, context=None):
    """Assert exact equality with bounded hashes/context and a first-byte locator."""
    identical = left == right
    if identical:
        return
    before, after = _encoded(left), _encoded(right)
    offset = next((i for i, (a, b) in enumerate(zip(before, after)) if a != b),
                  min(len(before), len(after)))
    comparison = {
        'base_sha256': hashlib.sha256(before).hexdigest(),
        'head_sha256': hashlib.sha256(after).hexdigest(),
        'first_difference': {
            'byte_offset': offset,
            'base_preview': repr(before[max(0, offset - 32):offset + 64]),
            'head_preview': repr(after[max(0, offset - 32):offset + 64]),
            'base_bytes': len(before), 'head_bytes': len(after),
        },
        'context': reprlib.repr(context)[:1200],
    }
    # Never assert left == right here: pytest would construct a quadratic diff.
    assert identical, comparison


def remove_checked_receipt_additions(events):
    """Project reviewed metadata for Thread stock and L41 historical controls.

    Mutates the supplied events only after checking the added values. Callers
    first check an exact, unprojected fingerprint. 37e7e496 marks voluntary
    movement; b82ae51e records HP before damage for fresh-drop consumers.
    All other event fields, including damage, remaining HP and paths, survive.
    These fixtures contain ordinary voluntary movement, not forced movement.
    """
    for event in events:
        payload = event['payload']
        if event['event_type'] == 'MOVEMENT_COMMITTED':
            assert payload['forced'] is False
            del payload['forced']
        if event['event_type'] == 'DAMAGE_COMMITTED':
            before = payload['hp_before']
            assert type(before) is int and before >= 0
            assert payload['remaining_hp'] == max(0, before - payload['hp_damage'])
            del payload['hp_before']
