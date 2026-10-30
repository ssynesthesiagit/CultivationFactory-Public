"""A2-fate: Empress of Hidden Growth Auspice's Release (add the caster's Proficiency Bonus after the roll, before the outcome).

The grant and the bearer's roll go through the real table (TabletopService -> CombatService execute_intent); the answer to the
Release prompt is the table's own choice transport. Both the bonus and the ended Auspice are read back after a cold reload.
"""
import pytest

from combat.ext import fate_riders as F
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_r9i_choices import action, finish_turn, resolve
from tests.test_r9i_fate_persistence import ALLY, FOE, PLAYER, fixture
from tests.test_r9i_karma_persistence import act

EMPRESS = "TAL_FATE_EMPRESS_OF_HIDDEN_GROWTH_AUSPICE"


def _grant_and_reach_ally_turn(table, mid):
    while table.state(mid)["menu"]["actor_id"] != PLAYER:
        finish_turn(table, mid)
    resolve(lambda answers: act(table, mid, action(table, mid, "Empress of Hidden Growth Auspice", ALLY), answers), {})
    finish_turn(table, mid)
    while table.state(mid)["menu"]["actor_id"] != ALLY:
        finish_turn(table, mid)


@pytest.mark.parametrize("release", [False, True])
def test_empress_release_adds_proficiency_bonus_once_and_ends_the_auspice(tmp_path, release):
    combat, table, mid = fixture(tmp_path, EMPRESS)
    _grant_and_reach_ally_turn(table, mid)
    held = F._auspice(combat._load_session(mid).engine.state.actors[ALLY], "empress")
    assert held is not None
    pb = int(held.data["pb"])

    cid = action(table, mid, "Dagger", FOE)
    seen = resolve(lambda answers: act(table, mid, cid, answers), {"choice:needle.empress_release": ["release"] if release else None})
    assert ("choice:needle.empress_release" in seen) is True

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    bonuses = [e for e in loaded.engine.events
               if e.event_type == "D20_REWRITTEN" and e.payload.get("operation") == "bonus"
               and e.source_definition_id == "fate:optional_roll_bonus"]
    still_held = F._auspice(loaded.engine.state.actors[ALLY], "empress")
    if release:
        assert still_held is None
        assert len(bonuses) == 1 and bonuses[0].payload["bonus"] == pb
    else:
        assert still_held is not None
        assert bonuses == []


def test_empress_grant_count_survives_cold_reload_and_the_cap_withholds_the_offer(tmp_path):
    from types import SimpleNamespace

    combat, table, mid = fixture(tmp_path, EMPRESS)
    _grant_and_reach_ally_turn(table, mid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    caster = loaded.engine.state.actors[PLAYER]
    assert caster.turn_flags[F._empress_key(ALLY)] == 1
    assert loaded.mechanical.replay()["status"] == "PASS"
    action = next(a for a in loaded.engine.action_catalog.values()
                  if ((a.parameters or {}).get("typed") or {}).get("source") == EMPRESS)
    candidate = SimpleNamespace(target_ids=[ALLY])
    assert F.empress_per_creature_cap(loaded.engine, caster, candidate, action) is None
    caster.turn_flags[F._empress_key(ALLY)] = caster.proficiency_bonus
    assert F.empress_per_creature_cap(loaded.engine, caster, candidate, action) is False


def _turn(table, mid, actor):
    for _ in range(40):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        finish_turn(table, mid)
    raise AssertionError("Actor's turn did not arrive")


def _cold(tmp_path, mid):
    from combat.tabletop_service import TabletopService

    combat = CombatService(ROOT, tmp_path)
    loaded = combat._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    return combat, TabletopService(combat, tmp_path), loaded


def test_repeated_real_grants_remove_only_capped_recipient_after_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, EMPRESS, caster_pb=2)
    for count in (1, 2):
        _turn(table, mid, PLAYER)
        resolve(lambda answers: act(table, mid, action(table, mid, "Empress of Hidden Growth Auspice", ALLY), answers), {})
        combat, table, loaded = _cold(tmp_path, mid)
        assert loaded.engine.state.actors[PLAYER].turn_flags[F._empress_key(ALLY)] == count
        finish_turn(table, mid)
    _turn(table, mid, PLAYER)
    combat, table, loaded = _cold(tmp_path, mid)
    recipients = [o["target_ids"] for g in table.state(mid)["menu"]["actions"]
                  if "Empress of Hidden Growth Auspice" in g["label"] for o in g["options"]]
    assert [ALLY] not in recipients
    assert [PLAYER] in recipients


@pytest.mark.parametrize("rank", [1, 2])
def test_release_on_real_skill_check_respects_recorded_expertise(tmp_path, rank):
    combat, table, mid = fixture(tmp_path, EMPRESS, ally_talents=["TAL_SCOUNDREL_DIRTY_TRICK"],
                               ally_skills=[{"skill": "Sleight of Hand", "bonus": 2 + rank * 4,
                                             "proficiency_multiplier": rank}])
    _grant_and_reach_ally_turn(table, mid)
    combat, table, loaded = _cold(tmp_path, mid)
    assert next(b for b in loaded.engine.typed_bundle_documents if b["actor_id"] == ALLY)["skill_proficiency"]["Sleight of Hand"] == rank
    cid = action(table, mid, "DIRTY TRICK", FOE)
    seen = resolve(lambda answers: act(table, mid, cid, answers), {"choice:needle.empress_release": ["release"]})
    assert ("choice:needle.empress_release" in seen) == (rank == 1)
    _, _, loaded = _cold(tmp_path, mid)
    assert any(r.actor_id == ALLY and r.reason.endswith(":SLEIGHT_OF_HAND") for r in loaded.engine.rolls)
    assert (F._auspice(loaded.engine.state.actors[ALLY], "empress") is None) == (rank == 1)
    bonuses = [e for e in loaded.engine.events if e.event_type == "D20_REWRITTEN"
               and e.source_definition_id == "fate:optional_roll_bonus"]
    assert len(bonuses) == (1 if rank == 1 else 0)


def test_release_text_uses_caster_pb_and_has_no_reaction_cost_or_second_use(tmp_path):
    combat, table, mid = fixture(tmp_path, EMPRESS, caster_pb=2, ally_pb=4)
    _grant_and_reach_ally_turn(table, mid)
    _, _, loaded = _cold(tmp_path, mid)
    pill = F._auspice(loaded.engine.state.actors[ALLY], "empress").data["label"]
    assert "Empress of Hidden Growth Auspice" in pill
    assert "caster's Proficiency Bonus" in pill and "no action or Reaction cost" in pill
    assert "Concentration ends" in pill
    assert pill in str(table.state(mid)["presentation"])
    prompts = []

    def send(answers):
        result = act(table, mid, cid, answers)
        if result["status"] == "REACTION_REQUIRED" and result["reaction"]["context"]["reaction_source_id"] == "choice:needle.empress_release":
            prompts.append(result["reaction"]["moment"])
        return result

    cid = action(table, mid, "Bi Shou (Dagger) attack", FOE)
    resolve(send, {"choice:needle.empress_release": ["release"]})
    assert prompts and all("caster's Proficiency Bonus (+2)" in p and "No action or Reaction cost" in p for p in prompts)
    _, _, loaded = _cold(tmp_path, mid)
    assert loaded.engine.state.actors[ALLY].reaction_available
    finish_turn(table, mid)
    _turn(table, mid, ALLY)
    cid = action(table, mid, "Bi Shou (Dagger) attack", FOE)
    assert "choice:needle.empress_release" not in resolve(send, {"choice:needle.empress_release": ["release"]})
    _cold(tmp_path, mid)


def test_player_release_contest_prompt_during_ai_opponent_action(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter

    reaction = "reaction:typed.TAL_RETRIBUTION_INTERCEPTING_STRIKE"
    combat, table, mid = fixture(tmp_path, EMPRESS, ally_talents=["TAL_RETRIBUTION_INTERCEPTING_STRIKE"], ally_ask=True)
    _grant_and_reach_ally_turn(table, mid)
    finish_turn(table, mid)
    _turn(table, mid, FOE)
    cid = action(table, mid, "Bi Shou (Dagger) attack", ALLY)
    real = combat.controller

    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    prompts = []

    def send(answers):
        answers = [{k: v for k, v in answer.items() if k != "option_ids"}
                   if answer.get("reaction_source_id") == reaction else answer for answer in answers]
        result = table.auto_step(mid, 0, answers)
        if result["status"] == "REACTION_REQUIRED" and result["reaction"]["context"]["reaction_source_id"] == "choice:needle.empress_release":
            assert result["reaction"]["context"]["reactor_id"] == ALLY
            prompts.append(result["reaction"]["moment"])
        return result

    seen = resolve(send, {reaction: ["USE"], "choice:needle.empress_release": ["release"]})
    assert "choice:needle.empress_release" in seen
    assert prompts and all("Intercepting Strike" in p for p in prompts)
    _, _, loaded = _cold(tmp_path, mid)
    assert F._auspice(loaded.engine.state.actors[ALLY], "empress") is None
    assert any(e.event_type == "D20_REWRITTEN" and e.payload.get("original", {}).get("reason") == "REACTION_CONTEST"
               for e in loaded.engine.events)


def test_release_on_real_hazard_save_commits_and_cold_reloads(tmp_path, monkeypatch):
    from combat.tabletop import TabletopMapStore
    from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY as A

    original_save = TabletopMapStore.save

    def save_map(store, document):
        return original_save(store, {**document, "starts": {"team1": [[3, 4], [3, 5]], "team2": [[9, 4]]},
                                     "terrain": [{"type": "QI_HAZARD", "cells": [[3, 6]]}]})

    monkeypatch.setattr(TabletopMapStore, "save", save_map)
    combat, table, mid = table_fight(tmp_path, [EMPRESS], ally_talents=[], ask=True)
    resolve(lambda answers: act(table, mid, action(table, mid, "Empress of Hidden Growth Auspice", A), answers), {})
    finish_turn(table, mid)
    _turn(table, mid, A)
    move = next(m for m in table.state(mid)["menu"]["moves"] if m["destination"] == {"x": 3, "y": 6})
    seen = resolve(lambda answers: act(table, mid, move["candidate_id"], answers), {"choice:needle.empress_release": ["release"]})
    assert "choice:needle.empress_release" in seen
    _, _, loaded = _cold(tmp_path, mid)
    assert F._auspice(loaded.engine.state.actors[A], "empress") is None
    bonuses = [e for e in loaded.engine.events if e.event_type == "D20_REWRITTEN"
               and e.source_definition_id == "fate:optional_roll_bonus"]
    assert len(bonuses) == 1 and bonuses[0].payload["original"]["reason"] == "QI_HAZARD_DEX_SAVE"
    assert bonuses[0].payload["bonus"] == loaded.engine.state.actors[LEFT].proficiency_bonus
