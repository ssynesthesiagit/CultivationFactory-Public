"""Ask me must reach the player for every reaction, not only the ones nothing swallows (owner playtest 2026-09-29, live fight
Tabik Damu on manual control and Ask me: "the reaction that came up was stamina guard and NOT all these different flowing
river responses").

The service pauses a preview by raising the choice provider's pause out of the engine (combat/gate5_service.py
_ReactionRequired). Every generic reaction row in combat/typed_reactions.py, and every plug-in hook run through
combat/ext ``run``, is wrapped so that a broken row can never end a fight -- and that wrapper caught the pause too,
logged "could not run: COMBAT_REACTION_DECISION_REQUIRED", and left the policy controller to decline for the player. Only
Stamina Guard (an engine reaction, not a generic row) ever prompted. The pause is now a combat.ext.ControllerPause the
wrappers let through, and a genuine bug in a row still becomes a GM line.
"""

import json
import zipfile
from pathlib import Path

import pytest

from combat import ext, typed_reactions
from combat.ext import ControllerPause, flowing_river
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_models import ReactionDecision
from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService, _ReactionRequired
from combat.tabletop import ButtonStore
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
RIVER = "3b1f7c52-0d6e-4a48-9b7a-2f5d81c04e19"
FOE = "9a4e2d61-7c38-4f05-b1d2-6e0a93b57c48"
RIVER_ID, FOE_ID = FACTORY_ACTOR_PREFIX + RIVER, FACTORY_ACTOR_PREFIX + FOE
RESPONSE = "reaction:typed.TAL_FLOWING_RIVER_FLOWING_RESPONSE"


def _install(userdata: Path, project_id: str, spheres: list[str], talents: list[str]) -> None:
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": spheres, "learned_talent_record_ids": talents}}
    folder = userdata / "portable_characters" / project_id
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))


def _fight(tmp_path: Path):
    _install(tmp_path, RIVER, ["tianxia.sphere.flowing_river"],
             ["TAL_FLOWING_RIVER_FLOWING_RESPONSE", "TAL_FLOWING_RIVER_HAND_ON_THE_WRIST"])
    _install(tmp_path, FOE, [], [])
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(RIVER, {"mode": "ask"}, set())
    service = CombatService(ROOT, tmp_path)
    match_id = service.create_factory_match(project_ids=[RIVER], opponent_actor_ids=[FOE_ID], match_seed="ASK-ME-FLOWING",
                                            control_modes={RIVER_ID: "MANUAL", FOE_ID: "LOCAL_AUTO"})["match_id"]
    session = service._load_session(match_id)
    assert session.engine.typed_ask_reactors == frozenset({RIVER_ID})  # the foe is on Auto, the river fighter is asked
    return service, session, service._read_metadata(match_id, session)


def _foe_acts(session, action_suffix: str):
    """The foe, standing next to the river fighter and on its own turn, ready to do the action ending ``action_suffix``."""
    engine = session.engine
    river, foe = engine.state.actors[RIVER_ID], engine.state.actors[FOE_ID]
    foe.position = Position(x=river.position.x - 1, y=river.position.y)
    engine.state.current_slot_index = engine.state.initiative_order.index(FOE_ID)
    engine.state.current_actor_id = FOE_ID
    engine._system_start_turn()
    river.reaction_available = True
    candidate = next(c for c in engine.legal_candidates()
                     if c.actor_id == FOE_ID and RIVER_ID in (c.target_ids or ())
                     and c.source_definition_id.endswith(action_suffix))
    return ActionIntent(intent_id="ask-me-flowing", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=FOE_ID, target_ids=candidate.target_ids)


def _play(service, session, metadata, intent, selections):
    """Run the action the way the table does: answer each prompt the fight stops on, from ``selections`` (one per prompt in
    order; anything after them is a Pass). Returns (the prompts in the order they came, the finished preview)."""
    answers, prompts = [], []
    for _ in range(20):
        try:
            return prompts, service._run_preview(session, metadata, intent, tuple(answers))
        except _ReactionRequired as needed:
            context = needed.context
            prompts.append((context.checkpoint.split("@")[0], context.reaction_source_id))
            answer = selections[len(prompts) - 1] if len(prompts) <= len(selections) else "DECLINE"
            answers.append(ReactionDecision(checkpoint=context.checkpoint, reactor_id=context.reactor_id,
                                            reaction_source_id=context.reaction_source_id, selection=answer))
    raise AssertionError(f"never finished; asked {prompts}")


def _swallowed(preview):
    return [e["payload"]["rider"] for e in preview["events"] if e["event_type"] == "GM_RIDER" and "could not run" in json.dumps(e)]


def _opened(preview, reaction):
    return [e for e in preview["events"] if e["event_type"] == "REACTION_WINDOW_OPENED" and e.get("source_definition_id") == reaction]


def test_a_melee_attack_on_an_ask_me_river_fighter_stops_for_flowing_response(tmp_path):
    service, session, metadata = _fight(tmp_path)
    intent = _foe_acts(session, ".weapon.bi_shou")
    prompts, done = _play(service, session, metadata, intent, ["DECLINE"])
    assert prompts and prompts[0] == ("TYPED:ATTACK_DECLARED", RESPONSE)  # the first thing the player is asked
    assert not _swallowed(done)  # nothing was quietly skipped as "could not run"
    assert not _opened(done, flowing_river.RESPONSE)  # declined: the response was not used


def test_using_flowing_response_when_asked_runs_it(tmp_path):
    service, session, metadata = _fight(tmp_path)
    intent = _foe_acts(session, ".weapon.bi_shou")
    prompts, done = _play(service, session, metadata, intent, ["USE"])
    assert prompts[0] == ("TYPED:ATTACK_DECLARED", RESPONSE)
    assert not _swallowed(done)
    assert _opened(done, flowing_river.RESPONSE)  # the Reaction window opened, and the answer was the player's


def test_a_shove_asks_for_flowing_response_too(tmp_path):
    """The second trigger (a creature within reach forces a save to move or knock you Prone) runs through the plug-in's
    ``save`` hook, which combat.ext.run used to wrap and swallow the same way."""
    service, session, metadata = _fight(tmp_path)
    intent = _foe_acts(session, ".unarmed.shove_prone")
    prompts, done = _play(service, session, metadata, intent, ["USE"])
    assert ("TYPED:SAVE_PENDING", RESPONSE) in prompts
    assert not _swallowed(done)
    assert _opened(done, flowing_river.RESPONSE)


def test_the_pause_is_the_shared_marker_and_a_hook_lets_it_through():
    assert issubclass(_ReactionRequired, ControllerPause)
    ext._load()
    ext._HOOKS["ask_me_probe"] = [lambda: (_ for _ in ()).throw(ControllerPause("waiting"))]
    try:
        with pytest.raises(ControllerPause):
            ext.run("ask_me_probe")
    finally:
        del ext._HOOKS["ask_me_probe"]


def test_a_genuinely_broken_hook_or_row_still_never_ends_the_fight():
    ext._load()

    def broken():
        raise ValueError("a bug in a plug-in")

    ext._HOOKS["ask_me_probe"] = [broken, lambda: "still runs"]
    try:
        assert ext.run("ask_me_probe") == ["still runs"]
    finally:
        del ext._HOOKS["ask_me_probe"]

    class Engine:
        def __init__(self):
            self.events = []

        def _append_event(self, kind, source, **fields):
            self.events.append((kind, fields["payload"]["rider"]))

    class Actor:
        entity_id = "actor:a"

    engine = Engine()
    typed_reactions._log_bad_row(engine, Actor(), None, {"feature_id": "X", "name": "Row"}, ValueError("boom"))
    assert engine.events == [("GM_RIDER", "Row could not run: boom")]
    with pytest.raises(ControllerPause):
        typed_reactions._log_bad_row(engine, Actor(), None, {"feature_id": "X", "name": "Row"}, ControllerPause("waiting"))
    assert len(engine.events) == 1
