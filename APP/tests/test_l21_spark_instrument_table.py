"""Spark lifecycle through real table actions and disk reloads, without state injection."""

import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r1i_service_support import force_ai_candidate

CASTER = FACTORY_ACTOR_PREFIX + "l21-caster"
OTHER = FACTORY_ACTOR_PREFIX + "l21-other"
LISTENER = FACTORY_ACTOR_PREFIX + "l21-listener"
TARGET = FACTORY_ACTOR_PREFIX + "l21-target"
HIDERS = [FACTORY_ACTOR_PREFIX + f"l21-hidden-{i}" for i in range(3)]
SPARK = "TAL_LIGHTNING_SPARK_INSTRUMENT_METHOD"
LASH = "TAL_LIGHTNING_LIGHTNING_LASH"


def _fixture(tmp_path, *, listener_first=False, overlapping=False, listener_sense=False,
             searched_listener=False):
    # Hidden enemies stand behind the arena's northwest pillars. High Stealth
    # guarantees Hide succeeds and ordinary Search cannot reveal them, so two
    # committed Searches remain legal. These are sheet stats, not conditions.
    ids = [*HIDERS[:3 if overlapping else 1], CASTER, OTHER, LISTENER, TARGET]
    positions = {CASTER: {"x": 3, "y": 3}, OTHER: {"x": 3, "y": 4},
                 LISTENER: {"x": 5, "y": 4}, TARGET: {"x": 5, "y": 3},
                 **{aid: {"x": 8 + i // 2, "y": 3 + i % 2} for i, aid in enumerate(HIDERS)}}
    if searched_listener:
        positions.update({CASTER: {"x": 5, "y": 5}, LISTENER: {"x": 8, "y": 4},
                          TARGET: {"x": 8, "y": 5}, HIDERS[0]: {"x": 3, "y": 3}})
    bonuses = {CASTER: 60, OTHER: 40, LISTENER: 80 if listener_first else 20, TARGET: -40,
               **{aid: 200 + i * 30 for i, aid in enumerate(HIDERS)}}
    bundles = []
    for aid in ids:
        talents = [LASH, SPARK] if aid in (CASTER, OTHER) else []
        if listener_sense and aid == LISTENER:
            talents = ["tianxia.subpath.qi.mountain_core_cultivator.feature.stone_sense"]
        doc = sheet(talents, cl=17, dc=50)
        doc["identity"]["display_name"] = aid.removeprefix(FACTORY_ACTOR_PREFIX).removeprefix("l21-").title()
        stats = doc["ability_scores_and_statistics"]
        stats["initiative"] = {"bonus": bonuses[aid]}
        stats["hit_points"]["maximum"] = 500
        stats["technique_attack_bonus"] = 100
        stats["skills"] = [{"skill": "Stealth", "bonus": 50}, {"skill": "Perception", "bonus": 0}]
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=aid, reaction_plan={"ask": True}))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids, {aid: "team:b" if aid in (LISTENER, TARGET) else "team:a" for aid in ids},
        {aid: positions[aid] for aid in ids}, combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        ids, [], control_modes={aid: "MANUAL" for aid in ids}, match_seed="SOL21-SPARK",
        display_name="Spark table regression", maximum_rounds=10)["match_id"]
    for aid in reversed(HIDERS[:3 if overlapping else 1]):
        assert table.state(mid)["menu"]["actor_id"] == aid
        _act(table, mid, _candidate(table, mid, "Hide"))
        _end(table, mid)
    if listener_first:
        assert table.state(mid)["menu"]["actor_id"] == LISTENER
        if searched_listener:
            _act(table, mid, _candidate(table, mid, "Hide"))
        _end(table, mid)
    assert table.state(mid)["menu"]["actor_id"] == CASTER
    return combat, table, mid


def _candidate(table, mid, label, target=None):
    return next(option["candidate_id"] for group in table.state(mid)["menu"]["actions"]
                if group["label"] == label for option in group["options"]
                if target is None or target in option.get("target_ids", []))


def _act(table, mid, cid, *, auto=False, expect_choice=False):
    answers, choices = [], []
    for _ in range(16):
        menu = table.state(mid)["menu"]
        result = (table.auto_step(mid, 0, answers) if auto else
                  table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers))
        if result["status"] == "COMMITTED":
            assert bool(choices) == expect_choice
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt.get("choice"):
            assert LISTENER in [option["id"] for option in prompt["choice"]["options"]]
            assert "Spark-Instrument" in str(prompt)
            assert "Lightning Lash" in str(prompt)
            assert "Target" in str(prompt) and "Listener" in str(prompt)
            choices.append(prompt)
            answer.update(selection="USE", option_ids=[LISTENER])
        answers.append(answer)
    raise AssertionError("too many prompts")


def _end(table, mid):
    _act(table, mid, table.state(mid)["menu"]["end_turn"])


def _move(table, mid, x, y):
    cid = next(row["candidate_id"] for row in table.state(mid)["menu"]["moves"]
               if row["destination"] == {"x": x, "y": y})
    _act(table, mid, cid)


def _reload(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    session = combat._load_session(mid)
    assert session.mechanical.replay()["status"] == "PASS"
    return combat, TabletopService(combat, tmp_path), session.engine


def _sparks(engine):
    return sorted((condition for condition in engine.state.actors[LISTENER].conditions.values()
                   if (condition.data or {}).get("spark_instrument")), key=lambda c: c.applied_sequence)


def _cast(table, mid):
    # The Charge variant creates the mark before executing its Spark rider.
    _act(table, mid, _candidate(table, mid, "Lightning Lash: Charge + Spark-Instrument Method", TARGET),
         expect_choice=True)


@pytest.mark.parametrize("listener_first", [False, True])
def test_spark_live_reload_first_search_consumes_second_search_normal(tmp_path, listener_first):
    _combat, table, mid = _fixture(tmp_path, listener_first=listener_first)
    _cast(table, mid)
    _combat, table, engine = _reload(tmp_path, mid)
    [spark] = _sparks(engine)
    assert spark.source_actor_id == CASTER
    assert spark.expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert "Caster's next turn starts" in spark.data["label"]
    while table.state(mid)["menu"]["actor_id"] != LISTENER:
        _end(table, mid)
    # If the listener acted before its caster, its first opportunity is next
    # round, still before the caster's next turn. Either order must preserve it.
    _combat, table, engine = _reload(tmp_path, mid)
    assert [c.instance_id for c in _sparks(engine)] == [spark.instance_id]
    _act(table, mid, _candidate(table, mid, "Search"))
    _combat, table, engine = _reload(tmp_path, mid)
    assert not _sparks(engine)
    removed = [e for e in engine.events if e.event_type == "CONDITION_REMOVED"
               and e.payload.get("instance_id") == spark.instance_id]
    assert len(removed) == 1 and not removed[0].payload.get("checkpoint")
    _end(table, mid)
    while table.state(mid)["menu"]["actor_id"] != LISTENER:
        _end(table, mid)
    _act(table, mid, _candidate(table, mid, "Search"))
    _combat, _table, engine = _reload(tmp_path, mid)
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.actor_id == LISTENER]
    assert [e.payload["actor"]["mode"] for e in checks] == ["DISADVANTAGE", "NORMAL"]


@pytest.mark.parametrize("listener_first", [False, True])
def test_spark_unused_expiry_at_caster_next_turn_after_reload(tmp_path, listener_first):
    _combat, table, mid = _fixture(tmp_path, listener_first=listener_first)
    _cast(table, mid)
    _combat, table, engine = _reload(tmp_path, mid)
    [spark] = _sparks(engine)
    _end(table, mid)
    while table.state(mid)["menu"]["actor_id"] != CASTER:
        _combat, table, engine = _reload(tmp_path, mid)
        assert [c.instance_id for c in _sparks(engine)] == [spark.instance_id]
        _end(table, mid)
    _combat, _table, engine = _reload(tmp_path, mid)
    assert not _sparks(engine)
    [removed] = [e for e in engine.events if e.event_type == "CONDITION_REMOVED"
                 and e.payload.get("instance_id") == spark.instance_id]
    assert removed.actor_id == CASTER and removed.payload["checkpoint"] == "START_OF_TURN"
    assert not any(e.event_type == "CHECK_ROLLED" and e.actor_id == LISTENER for e in engine.events)


def test_overlapping_sparks_each_penalize_one_check_oldest_first(tmp_path):
    _combat, table, mid = _fixture(tmp_path, overlapping=True)
    # Real End Turn and Move commits cross the 99/100 application boundary.
    # Canonical disk maps sort their instance IDs lexically: the newer :100+
    # row then loads before the older :90+ row. FIFO must use applied_sequence.
    for _ in range(2):
        _end(table, mid)
        while table.state(mid)["menu"]["actor_id"] != CASTER:
            _end(table, mid)
    for _ in range(3):
        _move(table, mid, 3, 2)
        _move(table, mid, 3, 3)
    _cast(table, mid)
    _end(table, mid)
    assert table.state(mid)["menu"]["actor_id"] == OTHER
    _cast(table, mid)
    _combat, table, engine = _reload(tmp_path, mid)
    sparks = _sparks(engine)
    assert [c.source_actor_id for c in sparks] == [CASTER, OTHER]
    assert sparks[0].applied_sequence < 100 <= sparks[1].applied_sequence
    _end(table, mid)
    assert table.state(mid)["menu"]["actor_id"] == LISTENER
    _act(table, mid, _candidate(table, mid, "Search"))
    _combat, _table, engine = _reload(tmp_path, mid)
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.actor_id == LISTENER]
    assert [e.payload["actor"]["mode"] for e in checks] == ["DISADVANTAGE", "DISADVANTAGE", "NORMAL"]
    removed = [e for e in engine.events if e.event_type == "CONDITION_REMOVED"
               and e.payload.get("instance_id") in {c.instance_id for c in sparks}]
    assert [e.payload["instance_id"] for e in removed] == [c.instance_id for c in sparks]
    assert checks[0].sequence < removed[0].sequence < checks[1].sequence < removed[1].sequence < checks[2].sequence
    assert not _sparks(engine)


def test_ai_owned_spark_selects_automatically_on_auto_step(tmp_path):
    combat, table, mid = _fixture(tmp_path)
    cid = _candidate(table, mid, "Lightning Lash: Charge + Spark-Instrument Method", TARGET)
    force_ai_candidate(combat, mid, CASTER, cid)
    _act(table, mid, cid, auto=True)
    _combat, _table, engine = _reload(tmp_path, mid)
    assert len(_sparks(engine)) == 1


def test_sense_only_search_preserves_spark_after_commit_reload(tmp_path):
    _combat, table, mid = _fixture(tmp_path, listener_sense=True)
    _cast(table, mid)
    _combat, table, engine = _reload(tmp_path, mid)
    [spark] = _sparks(engine)
    while table.state(mid)["menu"]["actor_id"] != LISTENER:
        _end(table, mid)
    _act(table, mid, _candidate(table, mid, "Search"))
    _combat, _table, engine = _reload(tmp_path, mid)
    assert [c.instance_id for c in _sparks(engine)] == [spark.instance_id]
    [check] = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.actor_id == LISTENER]
    assert check.payload["by_sense"] and "actor" not in check.payload


def test_searching_a_spark_holder_does_not_consume_its_penalty(tmp_path):
    _combat, table, mid = _fixture(tmp_path, listener_first=True, searched_listener=True)
    _cast(table, mid)
    _combat, table, engine = _reload(tmp_path, mid)
    [spark] = _sparks(engine)
    _end(table, mid)
    assert table.state(mid)["menu"]["actor_id"] == OTHER
    _act(table, mid, _candidate(table, mid, "Search"))
    _combat, _table, engine = _reload(tmp_path, mid)
    assert [c.instance_id for c in _sparks(engine)] == [spark.instance_id]
    [check] = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.actor_id == OTHER]
    assert LISTENER in check.target_ids and check.payload["actor"]["mode"] == "NORMAL"


def test_spark_uncharged_flash_has_no_penalty(tmp_path):
    _combat, table, mid = _fixture(tmp_path)
    _act(table, mid, _candidate(table, mid, "Lightning Lash: Flash + Spark-Instrument Method", TARGET))
    _combat, _table, engine = _reload(tmp_path, mid)
    assert not _sparks(engine)
