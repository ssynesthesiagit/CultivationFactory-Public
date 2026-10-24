
import combat.typed_reactions as tr
from combat.ext.prior_event_resources import prior_event_only
from combat.ext.foundations3 import spirit_support_reaches
from tests import test_mgr_t15_shared_circuit_native as T

def test_probe_guard_rows(tmp_path):
    combat, table, mid = T.setup_native(tmp_path, feed=False)
    eng = T.reload(tmp_path, mid)
    o = eng.state.actors[T.OWNER]; a = eng.state.actors[T.ALLY]
    rt = [r for r in (getattr(eng, 'typed_reaction_rows', {}) or {}).get(T.OWNER, []) if r.get('feature_id') == T.GUARD]
    pv = [r for r in (getattr(eng, 'typed_passive_rows', {}) or {}).get(T.OWNER, []) if r.get('feature_id') == T.GUARD]
    gen = [r for r in tr._rows(eng, T.OWNER, 'generic') if r.get('feature_id') == T.GUARD]
    r0 = (gen or rt or pv or [{}])[0]
    msg = 'P rt%d pv%d gen%d held%s kind%s free%s cost%s pool%s prior%s dist%s sup%s' % (
        len(rt), len(pv), len(gen), r0.get('held_back'), r0.get('kind'), r0.get('free'),
        str(r0.get('costs'))[-40:], o.resources.get(T.POOL), prior_event_only(eng, o, T.POOL, 1, {}),
        eng._distance_actor_to_actor(o, a), spirit_support_reaches(eng, o, a))
    assert False, msg
