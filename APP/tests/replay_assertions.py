"""Compact failures for full replay captures; no pytest diff of huge operands.

Used by stock, cross-revision and save/reload guards. Equality is evaluated on
the original operands, so encoding here affects diagnostics only, never verdicts.
Historical controls may explicitly validate/project additive receipt fields with
the separate helper below; assert_replay_equal itself never normalizes operands.
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
        if (event['event_type'] == 'MOVEMENT_COMMITTED'
                and event.get('source_definition_id') == 'system:combat.movement'):
            assert payload['forced'] is False
            del payload['forced']
        if event['event_type'] == 'DAMAGE_COMMITTED':
            before = payload['hp_before']
            assert type(before) is int and before >= 0
            assert payload['remaining_hp'] == max(0, before - payload['hp_damage'])
            del payload['hp_before']


def remove_redundant_observation_refreshes(events):
    """Project 9bac375b's same-square freshness for historical L41 controls.

    Callers first check the complete current capture. Keep observation events
    and every changed position; remove only coordinates identical to a prior
    receipt. Explicit observations also advance that history, unchanged.
    """
    known = {}

    def positions(snapshot):
        assert isinstance(snapshot, dict)
        for side, targets in snapshot.items():
            assert isinstance(targets, dict)
            for target, position in targets.items():
                assert isinstance(position, dict) and {'x', 'y'} <= position.keys() <= {'x', 'y', 'z'}
                assert all(type(value) is int for value in position.values())
                yield side, target, position

    for event in events:
        payload = event['payload']
        for side, target, position in positions(payload.get('observations', {})):
            known.setdefault(side, {})[target] = position
        if 'observations_after' not in payload:
            continue
        changed = {}
        for side, target, position in positions(payload['observations_after']):
            if known.get(side, {}).get(target) != position:
                changed.setdefault(side, {})[target] = position
            known.setdefault(side, {})[target] = position
        if changed:
            payload['observations_after'] = changed
        else:
            del payload['observations_after']
