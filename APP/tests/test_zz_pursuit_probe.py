import json, zipfile
import combat.factory_compiler as fc
from combat.factory_compiler import compile_character
from tests.test_mgr_t15_pursuit_horizon import fight, OWNER, FOE, PURSUIT


def test_p10_diag(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path)
    folder = tmp_path / 'portable_characters' / OWNER.removeprefix('actor:factory.')
    with zipfile.ZipFile(folder / 'current.zip') as z:
        doc = json.loads(z.read('Tianxia_Owner_Character_Sheet_v1.json'))
    seen = []
    orig = fc._generic_reaction
    def wrap(mid_, mech, **kw):
        if 'pursuit' in mid_:
            seen.append('T=' + repr((mech.get('activation') or {}).get('trigger')) + ' MID=' + repr(mech.get('mechanic_id')) + ' SRC=' + str(mech.get('source'))[:120])
        return orig(mid_, mech, **kw)
    monkeypatch.setattr(fc, '_generic_reaction', wrap)
    compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    raise AssertionError('TT|' + ' ## '.join(seen))
