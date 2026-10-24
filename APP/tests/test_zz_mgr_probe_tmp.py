
import pathlib, tempfile
import combat.typed_reactions as tr
import combat.ext.foundations3 as f3
from tests import test_mgr_t15_shared_circuit_native as T

def _wrap(name):
    orig = getattr(tr, name)
    def w(*a, **k):
        out = orig(*a, **k)
        row = next((x.get('feature_id') for x in a if isinstance(x, dict) and 'feature_id' in x), None)
        print('CALL', name, 'row=', row, 'ret=', out if not hasattr(out, '__enter__') else type(out).__name__, flush=True)
        return out
    setattr(tr, name, w)
for n in ['_generic_in_range', '_can_trigger', '_generic_affordable', '_spend_generic']:
    _wrap(n)
origr = f3.spirit_support_reaches
def sr(engine, owner, subject):
    out = origr(engine, owner, subject)
    print('SUPPORT_REACH', owner.entity_id, subject.entity_id, engine._distance_actor_to_actor(owner, subject), out, flush=True)
    return out
f3.spirit_support_reaches = sr

def test_probe_guard(tmp_path):
    base = tmp_path
    combat, table, mid = T.setup_native(base, feed=False)
    eng = T.reload(base, mid)
    print('DEW', eng.state.actors[T.OWNER].resources, 'dist', eng._distance_actor_to_actor(eng.state.actors[T.OWNER], eng.state.actors[T.ALLY]), flush=True)
    cid = T.candidate(combat, mid, 'Native pressure', target=T.ALLY).candidate_id
    try:
        prompts = T.settle(table, mid, cid, choices={'reaction:typed.' + T.GUARD: 'first',
            'reaction:typed.' + T.FEED: 'first', 'choice:needle.foundations3_feed_accept': 'accept', T.CHOICE: 'advantage'})
        print('PROMPTS', [p['context'].get('reaction_source_id') for p in prompts], flush=True)
    except Exception as exc:
        import traceback; traceback.print_exc()
    eng = T.reload(base, mid)
    for e in eng.events:
        print('EV', e.sequence, e.event_type, e.source_definition_id, e.actor_id, str(e.payload)[:240], flush=True)
    print('DEW_END', eng.state.actors[T.OWNER].resources, flush=True)
