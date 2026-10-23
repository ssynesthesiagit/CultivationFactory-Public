import json, zipfile
from combat.factory_compiler import compile_character
from tests.test_mgr_t15_pursuit_horizon import fight, OWNER, FOE, PURSUIT


def test_p6_diag(tmp_path):
    combat, table, mid = fight(tmp_path)
    folder = tmp_path / 'portable_characters' / OWNER.removeprefix('actor:factory.')
    with zipfile.ZipFile(folder / 'current.zip') as z:
        doc = json.loads(z.read('Tianxia_Owner_Character_Sheet_v1.json'))
    b = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    diag = b.get('diagnostics') or {}
    sk = diag.get('skipped')
    s = json.dumps(sk)
    i = s.find('Pursuit')
    keys = [k for k in b if 'react' in k.lower()]
    raise AssertionError('DIAG|keys=' + str(keys) + ' ## skipped_hit=' + (s[max(0,i-300):i+200] if i>=0 else 'NONE: ' + s[:600]) + ' ## pathfeat=' + str(doc.get('path_and_subpath', {}).get('path_feature_record_ids')) + ' ## rr=' + str([ (r.get('feature_id'), r.get('block')) for r in (b.get('typed_reactions') or [])])[:500])
