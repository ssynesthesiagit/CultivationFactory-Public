import json, zipfile
import combat.factory_compiler as fc
from combat.reaction_triggers import classify_mechanic_all
from combat.factory_compiler import compile_character
from tests.test_mgr_t15_pursuit_horizon import fight, OWNER, FOE, PURSUIT


def test_p8_diag(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path)
    folder = tmp_path / 'portable_characters' / OWNER.removeprefix('actor:factory.')
    with zipfile.ZipFile(folder / 'current.zip') as z:
        doc = json.loads(z.read('Tianxia_Owner_Character_Sheet_v1.json'))
    seen = []
    orig = fc._generic_reaction
    def wrap(mid_, mech, **kw):
        if 'pursuit' in mid_:
            ms = classify_mechanic_all(mech)
            seen.append(f"KEYS={sorted(mech)} ACT={json.dumps(mech.get('activation'))[:500]} MATCH={[(m.kind, m.runnable) for m in ms]} MID={mech.get('mechanic_id')} RES={kw.get('pools') is not None} EFFS={json.dumps(mech.get('effects'))[:300]}")
        return orig(mid_, mech, **kw)
    monkeypatch.setattr(fc, '_generic_reaction', wrap)
    compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    raise AssertionError('KY|' + ' ## '.join(seen))
