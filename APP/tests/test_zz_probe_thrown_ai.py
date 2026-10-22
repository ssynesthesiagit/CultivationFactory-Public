"""TEMPORARY probe (never committed)."""
from combat import carry
from tests.test_thrown_possession import AXE, act, fixture, reload


def _short(cid):
    return cid.rsplit(":", 1)[-1][-6:]


def _comps(score):
    return ",".join(f"{c.component[:9]}={c.value}" for c in score.components if c.value)


def _fu(record):
    rows = [s for s in record.scored_alternatives if s.candidate_id not in {x.candidate_id for x in record.scored_alternatives[:3]}]
    return rows


def _snapshot(combat, mid):
    session = combat._load_session(mid)
    context = combat.ai_decision_context(session, progress_guard=True)
    choice = combat.controller.choose_primary_action(context)
    return context, choice


def _report(context, choice, tag):
    rec = choice.record
    fu_id = next((c.candidate_id for c in context.legal_candidates
                  if "#thrown" in c.source_definition_id and "weapon.fu" in c.source_definition_id), None)
    scored = {s.candidate_id: s for s in rec.scored_alternatives}
    fu = scored.get(fu_id)
    sel = scored[rec.selected_candidate_id]
    from combat.gate4_controller import _average_damage
    cand = next((c for c in context.legal_candidates if c.candidate_id == fu_id), None)
    return (f"{tag}|rel={context.policy.position_relative}|pol={context.policy.policy_id[-22:]}"
            f"|fu_avg={_average_damage(cand.source_definition_id) if cand else 'NA'}"
            f"|fu_meta={dict(cand.metadata).get('expected_damage') if cand else 'NA'}"
            f"|fu_know={dict(cand.metadata).get('target_knowledge') if cand else 'NA'}"
            f"|fu=[{_comps(fu) if fu else 'MISSING'}]|sel={_short(rec.selected_candidate_id)}[{_comps(sel)}]"
            f"|n={len(rec.scored_alternatives)}")


def test_probe_c_start(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, automatic=True)
    context, choice = _snapshot(combat, mid)
    raise AssertionError(_report(context, choice, "C"))


def test_probe_d_after_move(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, automatic=True)
    state = table.state(mid)
    table.auto_step(mid, state["last_sequence"], [])
    loaded = reload(tmp_path, mid)
    context, choice = _snapshot(combat, mid)
    raise AssertionError(_report(context, choice, "D")
                         + f"|pos={loaded.engine.state.actors[actor].position.model_dump(mode='json')}")
