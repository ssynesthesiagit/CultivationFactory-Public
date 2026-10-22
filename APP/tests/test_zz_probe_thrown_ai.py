"""TEMPORARY probe (never committed)."""
from combat.ai_tactics import TurnPlan
from tests.test_thrown_possession import fixture


def _s(cid):
    return (cid or "").rsplit(":", 1)[-1][-8:]


def test_probe_e_plan(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, automatic=True)
    session = combat._load_session(mid)
    context = combat.ai_decision_context(session, progress_guard=True)
    choice = combat.controller.choose_primary_action(context)
    plan = TurnPlan(context)
    scored = {s.candidate_id: s for s in choice.record.scored_alternatives}
    sel = choice.intent.candidate_id
    cand = next(c for c in context.legal_candidates if c.candidate_id == sel)
    base = [a for a in plan.actions if a.endswith("weapon.fu")]
    thrown = [a for a in plan.actions if a.endswith("weapon.fu#thrown")]
    def info(ids):
        if not ids:
            return "MISSING"
        i = plan.actions[ids[0]]
        return f"{i['damage']},{i['range']},{int(bool(i.get('ready', True)))},{i['economy']}"
    before = plan.range_error(plan.actor.position)
    after = plan.range_error(cand.destination) if cand.destination else None
    raise AssertionError(
        f"E|bands={plan.bands}|ar={plan.attack_range}|profband={context.policy.preferred_range_bands_ft}"
        f"|bav={plan.best_attack_value}|bid={_s(plan.best_attack_id)}|off={[_s(x) for x in plan.offered_strikes]}"
        f"|has={plan.has_strike}|fu={info(base)}|thr={info(thrown)}|wpos={plan.weights.get('position')}"
        f"|err={before},{after}|sel={_s(sel)}|dest={cand.destination}|mv={plan.movement_value(cand)}"
        f"|tot={scored[sel].total}")
