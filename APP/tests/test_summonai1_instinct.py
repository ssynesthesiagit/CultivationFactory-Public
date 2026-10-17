"""SUMMONAI1: an uncommanded summon takes an instinct turn, not a Dodge default.

Instinct order: follow a standing directive for one turn; otherwise attack the nearest reachable hostile; otherwise move
toward one; otherwise stay within 30 feet of the owner.  Every summon turn logs one SUMMON_TURN line in plain words.
"""

import json
from pathlib import Path

import pytest

from combat import summon_instinct, summons
from combat.gate2_runtime_models import ActionIntent
from combat.gate2_engine import Gate2Engine

from test_summons import OWNER, _engine, _turn_of

ROOT = Path(__file__).resolve().parents[1]
TEXT_RECORDS = ROOT / "authority" / "typed_mechanics" / "owner_text_edits.json"
NAMED = (
    "TAL_DEATH_LESSER_CORPSE_SERVANT_STAT_BLOCK",
    "TAL_DEATH_ROUSE_LESSER_DEAD",
    "TAL_DEATH_GRAVE_FORMATION",
    "tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation",
)


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
    assert "follows its order: hold" in _turns(engine, servant.entity_id)[-1]
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


def test_the_four_named_records_no_longer_say_dodge_by_default():
    doc = json.loads(TEXT_RECORDS.read_text(encoding="utf-8"))["records"]
    for key in NAMED:
        blob = json.dumps(doc[key], ensure_ascii=False)
        assert "Dodge" not in blob, key
        assert "instincts" in blob, key
        assert "it it " not in blob and "servant it " not in blob, key


def test_a_command_still_overrides_the_instinct_turn():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    servant = summons.owned_by(engine, OWNER)[0]
    _turn_of(engine, OWNER)
    summons.command(engine, engine.state.actors[OWNER], "corpse_servant", "system:test")
    assert servant.summon["commanded"] is True
    assert "directive" not in servant.summon  # a plain command sets no directive
