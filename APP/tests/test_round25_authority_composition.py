"""Auto-merges must retain one unambiguous set of reviewed source fields."""
import json
from collections import Counter
from pathlib import Path


def test_reviewed_authority_overrides_have_no_new_duplicate_json_keys():
    duplicates = []
    root = Path(__file__).resolve().parents[1] / 'authority/typed_mechanics/reviewed_final.d'
    for path in sorted(root.glob('*.json')):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    duplicates.append((path.name, key))
                result[key] = value
            return result
        json.loads(path.read_text(), object_pairs_hook=unique)
    # These two duplicate occurrences already existed at b221edf6. Removing
    # one is safe; integration must not add a new key or another occurrence.
    known = Counter([('review_sw-jester.json', 'riders'), ('zz_auto_h3.json', 'effects')])
    unexpected = Counter(duplicates) - known
    assert not unexpected, f'new duplicate authority keys: {dict(unexpected)}'
