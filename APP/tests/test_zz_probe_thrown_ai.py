"""TEMPORARY probe (never committed)."""
from combat import carry
from tests.test_thrown_possession import AXE, act, fixture, reload


def _short(cid):
    return cid.rsplit(":", 1)[-1][-28:]


def _ai_start(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, automatic=True)
    session = combat._load_session(mid)
    context = combat.ai_decision_context(session, progress_guard=True)
    choice = combat.controller.choose_primary_action(context)
    return combat, table, mid, actor, foe, context, choice


def test_probe_a_state(tmp_path):
    combat, table, mid, actor, foe, context, choice = _ai_start(tmp_path)
    original = reload(tmp_path, mid)
    start = original.engine.state.actors[actor].position.model_dump(mode="json")
    for _ in range(12):
        state = table.state(mid)
        if state["menu"]["actor_id"] == foe:
            act(table, mid, "end")
        else:
            table.auto_step(mid, state["last_sequence"], [])
        loaded = reload(tmp_path, mid)
        rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor
                 and e.source_definition_id.endswith(".weapon.fu#thrown")]
        if rolls:
            break
    loaded = reload(tmp_path, mid)
    me = loaded.engine.state.actors[actor]
    base = rolls[0].source_definition_id.split("#")[0] if rolls else "NONE"
    conds = [(c.condition_id.split(".")[-1], (c.data.get("disables_action") or "").rsplit(".", 1)[-1],
              c.data.get("dropped_at")) for c in me.conditions.values()
             if c.data.get("disables_action") or c.data.get("dropped_at")]
    combat.set_controller_mode(mid, actor_id=actor, controller_mode="MANUAL")
    act(table, mid, "end")
    act(table, mid, "end")
    offered = [s for s in (table.state(mid)["menu"].get("actions") or [])
               if "weapon.fu" in str(s.get("source_definition_id"))]
    raise AssertionError(
        f"A|start={start}|now={me.position.model_dump(mode='json')}|base={base.rsplit('.', 1)[-1]}"
        f"|conds={conds}|holds={carry.holds(loaded.engine, me, AXE)}|pick={carry.can_pick_up(loaded.engine, me, AXE)}"
        f"|offered={[o['source_definition_id'].rsplit('.', 1)[-1] for o in offered]}"
        f"|drops={[(i['x'], i['y']) for i in table._dropped_items(mid)]}")


def test_probe_b_choice(tmp_path):
    combat, table, mid, actor, foe, context, choice = _ai_start(tmp_path)
    rec = choice.record
    fu = [_short(c.candidate_id) for c in context.legal_candidates if "weapon.fu" in c.source_definition_id]
    tops = [(_short(s.candidate_id), s.total) for s in rec.scored_alternatives[:6]]
    raise AssertionError(
        f"B|sel={_short(rec.selected_candidate_id)}|legal_fu={fu}|top={tops}"
        f"|why={rec.explanation[:150]}")
