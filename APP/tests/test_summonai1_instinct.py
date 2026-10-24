"""SUMMONAI1: an uncommanded summon takes an instinct turn, not a Dodge default.

Instinct order: follow a standing directive for one turn; otherwise attack the nearest reachable hostile; otherwise move
toward one; otherwise stay within 30 feet of the owner.  Every summon turn logs one SUMMON_TURN line in plain words.
"""

from pathlib import Path

import pytest

from combat import summons
from combat.ext import summon_instinct
from combat.gate2_runtime_models import ActionIntent
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import Position

from test_summons import OWNER, _engine, _turn_of

ROOT = Path(__file__).resolve().parents[1]


def _turns(engine: Gate2Engine, actor_id: str) -> list[str]:
    return [e.payload["text"] for e in engine.events if e.event_type == "SUMMON_TURN" and e.actor_id == actor_id]


def test_an_uncommanded_servant_never_takes_the_dodge_default():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    servant = summons.owned_by(engine, OWNER)[0]
    _turn_of(engine, OWNER)
    engine.end_turn()
    assert not any(c.condition_id == "condition:core.dodge" for c in servant.conditions.values())
    assert any(e.event_type == "COMPANION_DEFAULT_APPLIED" and e.actor_id == servant.entity_id
               and e.payload["behavior"] == "INSTINCT" for e in engine.events)


def test_every_uncommanded_summon_turn_logs_what_it_did_and_why():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    servant = summons.owned_by(engine, OWNER)[0]
    _turn_of(engine, OWNER)
    engine.end_turn()
    lines = _turns(engine, servant.entity_id)
    assert len(lines) == 1 and servant.display_name in lines[0]
    assert any(word in lines[0] for word in ("attacks", "moves", "stays", "holds", "waits"))


def test_a_directive_is_one_turn_only_and_instincts_resume_after():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    servant = summons.owned_by(engine, OWNER)[0]
    summon_instinct.set_directive(servant.summon, "hold")
    _turn_of(engine, OWNER)
    engine.end_turn()
    assert "directive" not in servant.summon  # consumed by the one turn
    assert summon_instinct.ORDER_TEXT["hold"][1] in _turns(engine, servant.entity_id)[-1]
    _turn_of(engine, OWNER)
    engine.end_turn()
    assert "follows its order" not in _turns(engine, servant.entity_id)[-1]


def test_directive_kinds_are_validated():
    record = {}
    with pytest.raises(ValueError):
        summon_instinct.set_directive(record, "dance")
    with pytest.raises(ValueError):
        summon_instinct.set_directive(record, "attack")  # attack needs a target
    with pytest.raises(ValueError):
        summon_instinct.set_directive(record, "use")  # use needs an action id
    summon_instinct.set_directive(record, "attack", target_id="actor:x")
    assert record["directive"] == {"kind": "attack", "target_id": "actor:x", "action_id": None}


def test_a_command_still_overrides_the_instinct_turn():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    servant = summons.owned_by(engine, OWNER)[0]
    _turn_of(engine, OWNER)
    summons.command(engine, engine.state.actors[OWNER], "corpse_servant", "system:test")
    assert servant.summon["commanded"] is True
    assert "directive" not in servant.summon  # a plain command sets no directive


def test_a_remembered_enemy_is_never_treated_as_a_live_target(monkeypatch):
    from combat import target_knowledge
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    servant = summons.owned_by(engine, OWNER)[0]
    real = target_knowledge.knowledge

    def remembered(eng, viewer, target, action=None):
        if viewer.entity_id == servant.entity_id and target.entity_id == AN:
            return target_knowledge.Knowledge("LAST_OBSERVED", target.position)  # last seen, not in sight now
        return real(eng, viewer, target, action)

    monkeypatch.setattr(target_knowledge, "knowledge", remembered)
    _turn_of(engine, OWNER)
    engine.end_turn()
    text = _turns(engine, servant.entity_id)[-1]
    assert "attacks" not in text and "moves toward" not in text, text
    assert "no enemy in sight" in text, text


def test_the_servant_strikes_a_reachable_enemy_before_walking_to_the_nearest(monkeypatch):
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    servant = summons.owned_by(engine, OWNER)[0]
    sx, sy = servant.position.x, servant.position.y
    nearest = engine.state.actors[AN]
    nearest.position = Position(x=sx + 1, y=sy)
    # Sorts after AN, so with equal distances the nearest-first pick is AN.
    second = nearest.model_copy(update={"entity_id": "zz_second_foe", "display_name": "Second Foe",
                                        "position": Position(x=sx, y=sy + 1)})
    engine.state.actors[second.entity_id] = second
    engine.state.initiative_order.insert(engine.state.initiative_order.index(AN) + 1, second.entity_id)
    real = engine._action_candidates

    def unreachable_nearest(actor, action, **kwargs):
        return [c for c in real(actor, action, **kwargs) if nearest.entity_id not in c.target_ids]

    monkeypatch.setattr(engine, "_action_candidates", unreachable_nearest)
    _turn_of(engine, OWNER)
    engine.end_turn()
    text = _turns(engine, servant.entity_id)[-1]
    assert "attacks Second Foe" in text, text


def test_the_summon_turn_is_dispatched_through_the_ext_hook_not_the_core(monkeypatch):
    from combat.ext import summon_instinct as provider
    calls = []
    real = provider.take_turn
    monkeypatch.setattr(provider, "take_turn", lambda eng, actor: (calls.append(actor.entity_id), real(eng, actor)))
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    servant = summons.owned_by(engine, OWNER)[0]
    _turn_of(engine, OWNER)
    engine.end_turn()
    assert calls == [servant.entity_id]
    import ast
    tree = ast.parse((ROOT / "combat" / "summons.py").read_text(encoding="utf-8"))
    turn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "on_turn_start")
    assert not any(isinstance(node, ast.ImportFrom) and "summon_instinct" in (node.module or "")
                   for node in ast.walk(turn))
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "run_strict" and node.args
               and isinstance(node.args[0], ast.Constant) and node.args[0].value == "summon_default_turn"
               for node in ast.walk(turn))
