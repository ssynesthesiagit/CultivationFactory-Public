import json
from tests.ai_tiers_native_support import fight, context_for, selected, OWNER, FOE


def _brief(c):
    return [c.kind, c.movement_cost_ft, str(c.destination), str(getattr(c, "explanation", ""))[:90]]


def test_diag_flier(tmp_path):
    combat, _, session = fight(tmp_path, flight=True, melee=True, seed="AISPEED1")
    actor = session.engine.state.actors[OWNER]
    actor.action_available = actor.bonus_action_available = False
    ctx = context_for(combat, session)
    choice, cand = selected(ctx)
    out = {"first": _brief(cand), "mv_before": actor.movement_remaining_ft, "speed": actor.speed_ft,
           "n_legal1": len(ctx.legal_candidates), "kinds1": sorted({c.kind for c in ctx.legal_candidates})}
    session.engine.execute_intent(choice.intent)
    out["pos"] = [actor.position.x, actor.position.y]
    out["foe"] = [session.engine.state.actors[FOE].position.x, session.engine.state.actors[FOE].position.y]
    out["dist_after"] = session.engine._distance_actor_to_actor(actor, session.engine.state.actors[FOE])
    out["mv_after"] = actor.movement_remaining_ft
    out["cur"] = session.engine.state.current_actor_id
    ctx2 = context_for(combat, session)
    choice2, cand2 = selected(ctx2)
    out["second"] = _brief(cand2)
    out["n_legal2"] = len(ctx2.legal_candidates)
    out["kinds2"] = sorted({c.kind for c in ctx2.legal_candidates})
    out["choice2"] = str(choice2.intent.candidate_id)[:60]
    out["top2"] = sorted([(str(getattr(c, "score", "")), c.kind, str(c.destination), c.movement_cost_ft) for c in ctx2.legal_candidates], key=lambda t: t[0], reverse=True)[:6]
    assert False, "DIAG " + json.dumps(out, default=str, separators=(",", ":"))
