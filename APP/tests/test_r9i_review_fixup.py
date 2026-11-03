"""Court eligibility and readable prompts through the real table transport."""
import json

import pytest

from combat.ext import fate_riders as F
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_r9i_choices import action, resolve
from tests.test_r9i_karma_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY


@pytest.mark.parametrize("category", ["ATTACK", "CHECK", "SAVE", "QI_HAZARD_DEX_SAVE", "REACTION_COUNTER",
                                     "REACTION_CONTEST", "REACTION_CHANCE", "INITIATIVE",
                                     "FIRST_ARM_WEAPON_INTEGRITY_CON", "OMEN_DIE", "STORED_GLIMPSE"])
def test_court_only_consumes_for_printed_roll_categories(category):
    from tests.test_riders_lane9 import _fate_fight, _act, ALLY as A

    engine = _fate_fight([F.COURT])
    _act(engine, "Court of the Heavenly Ledger")
    zone = F._zones(engine, F.COURT)[0]
    roll = engine.roller.d20(modifier=3, actor_id=A, reason=category + ":test:unlisted")
    eligible = category in ("ATTACK", "CHECK", "SAVE", "QI_HAZARD_DEX_SAVE", "REACTION_COUNTER", "REACTION_CONTEST")
    assert (roll.total > roll.natural_result + 3) == eligible
    assert F._once_a_round(engine, ("court", zone.zone_id), consume=False) == (not eligible)


@pytest.mark.parametrize("category", ["REACTION_CHANCE", "ATTACK", "CHECK", "SAVE", "REACTION_COUNTER", "REACTION_CONTEST"])
def test_court_table_prompt_and_chance_nonconsumption(tmp_path, monkeypatch, category):
    combat, table, mid = table_fight(tmp_path, [F.COURT], ally_talents=[], ask=True)
    resolve(lambda answers: act(table, mid, action(table, mid, "Court of the Heavenly Ledger"), answers), {})
    reason = category + ":test:internal_source:DEX"

    def roll(engine):
        result = engine.roller.d20(modifier=0, actor_id=ALLY, reason=reason)
        engine._record_roll(result)

    on_hold(monkeypatch, roll)
    cid = action(table, mid, "Hold position")
    prompts = []

    def send(answers):
        result = act(table, mid, cid, answers)
        if result["status"] == "REACTION_REQUIRED":
            prompts.append(result["reaction"]["moment"])
        return result

    seen = resolve(send, {"choice:needle.court_bonus": ["add"]})
    eligible = category != "REACTION_CHANCE"
    assert ("choice:needle.court_bonus" in seen) == eligible
    if eligible:
        name = {"ATTACK": "attack roll", "CHECK": "ability check", "SAVE": "saving throw",
                "REACTION_COUNTER": "ability check", "REACTION_CONTEST": "attack roll or ability check"}[category]
        assert all("Court of the Heavenly Ledger" in p and "Ally" in p and name in p for p in prompts)
        assert all("test:" not in p and category + ":" not in p and "Hold position" not in p for p in prompts)
        # The approved player-text repair names the actual paying pool (Qi),
        # while this free bonus retains its timing, round limit and zero cost.
        assert all("before the outcome" in p and "Once per round" in p and "no additional Qi cost" in p for p in prompts)
        assert all(" CP " not in p for p in prompts)
    else:
        assert not prompts
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    zone = F._zones(loaded.engine, F.COURT)[0]
    assert F._once_a_round(loaded.engine, ("court", zone.zone_id), consume=False) == (not eligible)
    rolls = [r for r in loaded.engine.rolls if r.reason == reason]
    assert len(rolls) == 1
    assert (rolls[0].total > rolls[0].natural_result) == eligible
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("use", [False, True])
@pytest.mark.parametrize("talent,label,key", [(F.COURT, "Court of the Heavenly Ledger", "court"),
                                              (F.SERENDIPITY, "Serendipity Edict", "serendipity")])
def test_court_real_qi_hazard_move_commits_and_reloads(tmp_path, monkeypatch, use, talent, label, key):
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.tabletop import TabletopMapStore
    from tests.test_r9i_choices import finish_turn

    # Paint a real hazard before match creation; the accepted move invokes the
    # engine's normal hazard path, with no injected save or event callback.
    original_save = TabletopMapStore.save

    def save_map(store, document):
        # Keep the opponent out of reach so this move isolates hazard damage.
        return original_save(store, {**document, "starts": {**document["starts"], "team2": [[9, 4]]},
                                     "terrain": [{"type": "QI_HAZARD", "cells": [[3, 6]]}]})

    monkeypatch.setattr(TabletopMapStore, "save", save_map)
    combat, table, mid = table_fight(tmp_path, [talent], ally_talents=[], ask=True)
    resolve(lambda answers: act(table, mid, action(table, mid, label), answers), {})
    finish_turn(table, mid)
    while table.state(mid)["menu"]["actor_id"] != ALLY:
        finish_turn(table, mid)

    def die(roller, sides):
        counter = roller.counter
        roller.counter += 1
        return (8 if sides == 20 else 4), counter

    monkeypatch.setattr(DeterministicRollAuthority, "_die", die)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    hp = before["actors"][ALLY]["current_hp"]
    menu = table.state(mid)["menu"]
    move = next(m for m in menu["moves"] if m["destination"] == {"x": 3, "y": 6})
    prompts = []
    choice = "choice:needle." + ("court_bonus" if key == "court" else key)

    def send(answers):
        result = act(table, mid, move["candidate_id"], answers)
        if (result["status"] == "REACTION_REQUIRED"
                and result["reaction"]["context"]["reaction_source_id"] == choice):
            prompts.append(result["reaction"]["moment"])
        return result

    assert send([])["status"] == "REACTION_REQUIRED"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    seen = resolve(send, {choice: ["add"] if use else None})
    assert choice in seen
    assert prompts and all(label in p and "Ally" in p
                           and "Dexterity saving throw against the Qi hazard" in p for p in prompts)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    zone = F._zones(engine, talent)[0]
    assert F._once_a_round(engine, (key, zone.zone_id), consume=False) == (not use)
    saves = [r for r in engine.rolls if r.reason == "QI_HAZARD_DEX_SAVE"]
    assert len(saves) == 1 and saves[0].actor_id == ALLY
    assert saves[0].total == saves[0].natural_result + before["actors"][ALLY]["saving_throws"]["DEX"] + (4 if use else 0)
    assert (saves[0].total >= 12) == use
    assert engine.state.actors[ALLY].current_hp == hp - (0 if use else 4)
    assert any(e.event_type == "SAVE_ROLLED" and e.payload.get("reason") == "QI_HAZARD_DEX_SAVE"
               for e in engine.events)
    assert engine.state.actors[ALLY].position.model_dump() == {"x": 3, "y": 6}
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_formation_maze_rendered_gm_rider_uses_playable_rules():
    from combat.tabletop_service import _combat_preview

    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    text = " ".join(_combat_preview(authority["mechanics"]["tianxia.talent.formations.formation_maze"])["gm"])
    # Entry/start reactions and creature/anchor restrictions now run at the
    # table. Only doors/exits and the successful-save tax remain GM-managed.
    for phrase in ("GM: the owner may also choose a door or exit", "failed Wisdom save",
                   "until the start of the owner's next turn", "10 additional feet",
                   "next 10 feet of movement actually completed inside the array",
                   "refused steps and movement outside spend no tax"):
        assert phrase in text
    assert not any(phrase in text for phrase in ("transactional per-step pricing", "candidate veto", "entry choices"))
