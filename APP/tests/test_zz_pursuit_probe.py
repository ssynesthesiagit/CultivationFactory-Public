import json, zipfile
import combat.factory_compiler as fc
from combat.factory_compiler import compile_character
from tests.test_mgr_t15_pursuit_horizon import fight, OWNER, FOE, PURSUIT


def test_p7_diag(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path)
    folder = tmp_path / 'portable_characters' / OWNER.removeprefix('actor:factory.')
    with zipfile.ZipFile(folder / 'current.zip') as z:
        doc = json.loads(z.read('Tianxia_Owner_Character_Sheet_v1.json'))
    seen = []
    orig = fc._generic_reaction
    def wrap(mid_, mech, **kw):
        if 'pursuit' in mid_:
            diags = kw.get('diagnostics')
            n0 = len(diags) if diags is not None else -1
            r = orig(mid_, mech, **kw)
            seen.append(f"GR {mid_[-20:]} ret={'None' if r is None else 'row'} eff={len(mech.get('effects') or [])} opts={len(mech.get('options') or [])} econ={(mech.get('activation') or {}).get('economy')} diag={diags[n0:] if diags is not None else None} pb={kw.get('pb')} primary={kw.get('primary')} pools_type={type(kw.get('pools')).__name__}")
            return r
        return orig(mid_, mech, **kw)
    monkeypatch.setattr(fc, '_generic_reaction', wrap)
    b = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    raise AssertionError('GR|' + ' ## '.join(seen) + ' ## count=' + str(len(seen)))
