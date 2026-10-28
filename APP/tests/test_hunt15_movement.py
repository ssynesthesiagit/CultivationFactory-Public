"""Exact saved Soul Hook/Swaying Step checkpoint; private inputs stay external."""
import json
import os
from pathlib import Path
import shutil

import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.hunt15_support import ROOT


@pytest.mark.parametrize("ai", [False, True])
def test_soul_hook_swaying_step_checkpoint(tmp_path, ai):
    evidence = os.environ.get("HUNT15_EVIDENCE_ROOT")
    inputs = os.environ.get("HUNT15_CHARACTER_INPUTS")
    if not evidence or not inputs:
        pytest.skip("opt in with HUNT15_EVIDENCE_ROOT and HUNT15_CHARACTER_INPUTS")
    user = tmp_path / "saved-stall"
    shutil.copytree(Path(evidence) / "stall-save", user)
    folder = next((user / "Combat/Matches").iterdir())
    mid = json.loads((folder / "MatchLock.json").read_text())["match_id"]
    for bundle in json.loads((folder / "Typed_Character_Bundles.json").read_text()):
        pid = bundle["actor_id"].removeprefix("actor:factory.").split(".")[0]
        dest = user / "portable_characters" / pid
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(inputs) / pid / "current.zip", dest / "current.zip")
    combat, table = CombatService(ROOT, user), None
    table = TabletopService(combat, user)
    engine = combat._load_session(mid).engine
    aid = engine.state.current_actor_id
    actor = engine.state.actors[aid]
    assert engine._effective_speed(actor) == 0 and actor.movement_remaining_ft == 5
    assert not actor.action_available and not actor.bonus_action_available
    assert any(c.condition_id == "condition:typed.death_soul_hook" for c in actor.conditions.values())
    combat.set_controller_mode(mid, actor_id=aid, controller_mode="LOCAL_AUTO" if ai else "MANUAL")
    state = table.state(mid)
    assert not any(c.kind.value == "MOVE" for c in combat._load_session(mid).engine.legal_candidates())
    if not ai:
        assert not state["menu"]["moves"]
    before = engine.state.event_sequence
    answers = []
    for _ in range(20):
        state = table.state(mid)
        menu = state["menu"]
        result = table.auto_step(mid, state["last_sequence"], answers) if ai else table.act(
            mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            break
        prompt = result["reaction"]
        answers.append({**prompt["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, user)._load_session(mid)
    events = [e for e in loaded.engine.events if e.sequence > before]
    assert not any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == aid for e in events)
    assert any(e.event_type == "TURN_ENDED" and e.actor_id == aid for e in events)
    assert loaded.engine.state.current_actor_id != aid
    assert loaded.mechanical.replay()["status"] == "PASS"
