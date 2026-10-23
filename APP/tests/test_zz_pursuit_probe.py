import combat.typed_reactions as tr
from tests.test_mgr_t15_pursuit_horizon import fight, move, turn, OWNER, FOE, PURSUIT


def test_p4_trace(tmp_path, monkeypatch):
    log = []
    orig = tr.dispatch_creature_reactions
    def dcr(engine, subject, kind, **kw):
        if kind in ('moved',):
            from combat.ext.movement_clock import willing_distance
            rows = []
            for w in engine.state.actors.values():
                if w.entity_id in getattr(engine, 'typed_actor_ids', set()):
                    rows.append(f"{w.entity_id[-6:]}:" + ','.join(str(r.get('feature_id', r.get('kind')))[-16:] for r in tr._ordered_generic_rows(engine, w.entity_id, kind)))
            log.append(f"DCR {subject.entity_id[-6:]} {kind} moved={kw.get('moved_ft')} wd={willing_distance(engine, subject)} rows={rows}")
        return orig(engine, subject, kind, **kw)
    monkeypatch.setattr(tr, 'dispatch_creature_reactions', dcr)
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)
    log.append('after foe turn')
    engine, prompts = move(tmp_path, mid, 7)
    log.append(f"owner7 prompts={len(prompts)} " + str([(p.get('choice') or {}).get('name') or p.get('name') for p in prompts]))
    raise AssertionError("TRACE|" + " | ".join(log))
