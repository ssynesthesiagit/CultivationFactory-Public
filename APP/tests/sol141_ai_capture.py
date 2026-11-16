"""Headless base/head capture of existing persistent deterministic AI harnesses.

Run once per source tree and scenario, with PYTHONDONTWRITEBYTECODE=1:
  python tests/sol141_ai_capture.py APP_ROOT SCRATCH_DIR stock|shadow
stdout is canonical full state, committed events/rolls and candidate history.
Only the random storage match identifier is normalized by the existing harness.
No browser or live match is used. Scratch must be task-owned and removed.
"""
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
from tests.test_save_reload_equivalence import (
    _play, _bytes_of, _start_stock, _start_factory, _fight_id)

root = Path(sys.argv[2])
root.mkdir(parents=True, exist_ok=True)
scenario = sys.argv[3]

def shadow_start(folder):
    # The existing lane10 Shadowless Reversal duel, played to completion by
    # the real AI controller rather than directly executing a chosen hop.
    from tests.test_riders_lane10 import L4, SHADOW
    from combat.factory_compiler import compile_character
    ids = [_fight_id('left'), _fight_id('right')]
    docs = [L4.t._sheet(SHADOW, ['TAL_SHADOW_SHADOWLESS_REVERSAL'], L4.t.AXE_KIT, cl=17),
            L4.t._sheet(L4.BRUTE, [], L4.t.AXE_KIT, cl=17)]
    for aid, document in zip(ids, docs):
        document['identity']['display_name'] = aid.rsplit('-', 1)[-1].title()
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 400
        dest = folder / 'portable_characters' / aid.removeprefix('actor:factory.')
        dest.mkdir(parents=True)
        with zipfile.ZipFile(dest / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    bundles = [compile_character(doc, actor_id=aid) for aid, doc in zip(ids, docs)]
    return _start_factory(folder, 'shadow', ids, bundles)

capture = _play(root, shadow_start if scenario == 'shadow' else lambda p: _start_stock(p, 'GATE4-TEST'))
events = [event for decision in capture['events'] for event in decision]
if scenario == 'shadow':
    assert any(e['event_type'] == 'ZONE_CREATED' and 'shadow_silhouette' in json.dumps(e) for e in events), 'no reaction silhouette'
    assert any(e['event_type'] == 'MOVEMENT_COMMITTED' and e['payload'].get('teleport') for e in events), 'no reaction teleport'
print(_bytes_of(capture))
