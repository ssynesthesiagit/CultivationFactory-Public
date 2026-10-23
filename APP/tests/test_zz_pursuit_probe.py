import combat.ext.sky_treading as st
import combat.granted_movement as gm
from tests.test_mgr_t15_pursuit_horizon import fight, move, turn, OWNER, FOE, PURSUIT


def test_p3_trace(tmp_path, monkeypatch):
    log = []
    orig_pm = st._pursuit_move
    def pm(ctx, feet, gap, **kw):
        cands = st.choices(ctx.engine, ctx.actor, feet)
        log.append(f"PM feet={feet} gap={gap} cands={len(cands)} " + ';'.join(f"{c.destination.x},{c.destination.y}:{c.movement_cost_ft}" for c in cands[:8]))
        r = orig_pm(ctx, feet, gap, **kw)
        log.append(f"PM->{r}")
        return r
    orig_cc = gm._commit_candidate
    def cc(engine, actor, cand, source, feet, intent, *a, **kw):
        log.append(f"CC src={source[-12:]} feet={feet} path={[(p.x,p.y) for p in cand.canonical_path]}")
        r = orig_cc(engine, actor, cand, source, feet, intent, *a, **kw)
        log.append(f"CC->{r}")
        return r
    monkeypatch.setattr(st, '_pursuit_move', pm)
    monkeypatch.setattr(gm, '_commit_candidate', cc)
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)
    engine, prompts = move(tmp_path, mid, 7)
    engine, prompts = move(tmp_path, mid, 8, pending=True)
    evs = [f"{e.sequence}:{e.event_type}:{str(e.source_definition_id)[-14:]}:{str(e.actor_id)[-8:]}" for e in engine.events
           if e.event_type in ('MOVEMENT_COMMITTED','ATTACK_ROLLED','REACTION_RESOLVED','GM_RIDER','PASSIVE_TRIGGERED','PROMPT_OPENED','CHOICE_REQUESTED')]
    raise AssertionError("TRACE|" + " | ".join(log) + " ## " + " ".join(evs[-25:]))
