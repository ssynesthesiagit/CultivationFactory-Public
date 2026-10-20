import json
from tests.ai_tiers_native_support import fight, context_for, selected, OWNER, FOE


def _brief(c):
    d = c.model_dump(mode="json")
    return {k: d.get(k) for k in ("kind", "movement_cost_ft", "destination", "candidate_id", "label", "explanation", "score") if k in d} | {"keys": sorted(d)[:80]}


def test_diag_flier(tmp_path):
    combat, _, session = fight(tmp_path, flight=True, melee=True, seed="AISPEED1")
    actor = session.engine.state.actors[OWNER]
    actor.action_available = actor.bonus_action_available = False
    ctx = context_for(combat, session)
    choice, cand = selected(ctx)
    out = {"first": _brief(cand), "choice1": repr(choice)[:800], "mv_before": actor.movement_remaining_ft, "speed": actor.speed_ft,
           "legal1": [(c.kind, c.movement_cost_ft, str(c.destination)) for c in ctx.legal_candidates][:40], "n_legal1": len(ctx.legal_candidates)}
    session.engine.execute_intent(choice.intent)
    out["mv_after"] = actor.movement_remaining_ft
    out["pos"] = actor.position.model_dump(mode="json")
    out["foe_pos"] = session.engine.state.actors[FOE].position.model_dump(mode="json")
    out["dist_after"] = session.engine._distance_actor_to_actor(actor, session.engine.state.actors[FOE])
    ctx2 = context_for(combat, session)
    choice2, cand2 = selected(ctx2)
    out["second"] = _brief(cand2)
    out["choice2"] = repr(choice2)[:800]
    out["legal2"] = [(c.kind, c.movement_cost_ft, str(c.destination), str(getattr(c, "label", ""))[:80]) for c in ctx2.legal_candidates][:40]
    out["n_legal2"] = len(ctx2.legal_candidates)
    out["second_dist"] = session.engine._distance_actor_to_actor(actor, session.engine.state.actors[FOE], actor_position=cand2.destination) if cand2.destination is not None else None
    assert False, json.dumps(out, default=str, indent=1)
