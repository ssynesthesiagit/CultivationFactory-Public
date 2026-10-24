
import json
import combat.ext as ext
from tests import test_mgr_t15_shared_circuit_native as T

_LOG = []
_orig_run = ext.run
def _run(name, *a, **k):
    out = _orig_run(name, *a, **k)
    if name in ('reaction_geometry_allowed', 'reaction_reach', 'reaction_range_bonus'):
        _LOG.append([name, [getattr(x, 'entity_id', None) or getattr(x, 'feature_id', None) or (x.get('feature_id') if isinstance(x, dict) else str(x)[:40]) for x in a], str(out)[:200]])
    return out
ext.run = _run

def _dump(tmp_path, feed):
    combat, table, mid = T.setup_native(tmp_path, feed=feed)
    eng = T.reload(tmp_path, mid)
    o = eng.state.actors[T.OWNER]
    rows = [r for r in eng.typed_passive_rows.get(T.OWNER, []) if 'returning' in str(r.get('feature_id'))]
    d = {'feed': feed, 'pre_dew': o.resources.get(T.POOL), 'dist': eng._distance_actor_to_actor(o, eng.state.actors[T.ALLY]),
         'guard_rows': [{k: r.get(k) for k in ('feature_id','range_ft','range_reference','kind','free','cost','costs','resource','economy','requires_mark','source_within_reach','reaction_range_ft')} for r in rows],
         'owner_reaction_available': o.reaction_available}
    _LOG.clear()
    cid = T.candidate(combat, mid, 'Native pressure', target=T.ALLY).candidate_id
    try:
        prompts = T.settle(table, mid, cid, choices={'reaction:typed.' + T.GUARD: None if feed else 'first',
            'reaction:typed.' + T.FEED: 'first', 'choice:needle.foundations3_feed_accept': 'accept', T.CHOICE: 'advantage'})
        d['prompts'] = [{'src': p['context'].get('reaction_source_id'), 'keys': sorted(p.keys())} for p in prompts]
    except Exception as exc:
        d['settle_error'] = repr(exc)[:500]
    d['hooks'] = list(_LOG)
    eng = T.reload(tmp_path, mid)
    d['events'] = [[e.sequence, e.event_type, e.source_definition_id, e.actor_id, str(e.payload)[:160]] for e in eng.events
                   if e.event_type not in ('ACTION_DECLARED',) ][:120]
    d['owner_dew_end'] = eng.state.actors[T.OWNER].resources.get(T.POOL)
    return d

def test_probe_guard_dump(tmp_path):
    out = [_dump(tmp_path / 'g', False), _dump(tmp_path / 'f', True)]
    raise AssertionError('PROBE_DUMP ' + json.dumps(out, default=str))
