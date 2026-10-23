"""Hunt 5's close-range factory fixture, with a real Molten Terrain save."""

import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

FATE = "TAL_FATE_REWRITE_THE_DISASTER"
LAVA = "TAL_MAGMA_LAVA_FLOW"
PLAYER = FACTORY_ACTOR_PREFIX + "h5-player"
CASTER = FACTORY_ACTOR_PREFIX + "h5-foe"
PROTECTOR = FACTORY_ACTOR_PREFIX + "h5-protector"


@pytest.mark.parametrize("selection,natural", [("USE", 1), ("USE", 20), ("DECLINE", None)])
@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("ally_protection", [False, True])
def test_turn_start_rewrite_preview_commit_reload_replay(tmp_path, selection, natural, auto_turn, ally_protection):
    reactor = PROTECTOR if ally_protection else PLAYER
    sheets = [sheet([] if ally_protection else [FATE], cl=15), sheet([LAVA], cl=15, dc=20)]
    pids = ["h5-player", "h5-foe"]
    if ally_protection:
        sheets.append(sheet([FATE], cl=15))
        pids.append("h5-protector")
    for pid, document in zip(pids, sheets):
        document["identity"]["display_name"] = {
            "h5-player": "H5 Player", "h5-foe": "H5 Lava Caster", "h5-protector": "H5 Protector",
        }[pid]
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    actor_ids = [FACTORY_ACTOR_PREFIX + pid for pid in pids]
    bundles = [compile_character(document, actor_id=aid, reaction_plan={"ask": True} if aid == reactor else None)
               for document, aid in zip(sheets, actor_ids)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    positions = {PLAYER: {"x": 3, "y": 6}, CASTER: {"x": 4, "y": 6}}
    if ally_protection:
        positions[PROTECTOR] = {"x": 3, "y": 5}
    mid = combat._finish_factory_match(
        bundles, actor_ids, {aid: "team:opponents" if aid == CASTER else "team:factory" for aid in actor_ids},
        positions, arena, [aid for aid in actor_ids if aid != CASTER], [CASTER],
        control_modes={aid: "MANUAL" for aid in actor_ids}, match_seed="H5-TURN-START",
        display_name="Turn-start fixture", maximum_rounds=10)["match_id"]

    advancing_with_ai = False

    def send(cid, menu, answers=()):
        if advancing_with_ai:
            return table.auto_step(mid, 0, list(answers))
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))

    state = table.state(mid)
    for _ in range(len(actor_ids)):
        if state["menu"]["actor_id"] == CASTER:
            break
        state = send(state["menu"]["end_turn"], state["menu"])["state"]
    menu = state["menu"]
    assert menu["actor_id"] == CASTER
    group = next(g for g in menu["actions"] if "Lava Flow" in g["label"])
    cid = next(o["candidate_id"] for o in group["options"] if o.get("destination") == {"x": 3, "y": 6})
    answers = []
    for _ in range(8):
        result = send(cid, menu, answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt.get("choice"):
            choice = prompt["choice"]
            answer.update(selection="USE", option_ids=(choice.get("preferred") or [choice["options"][0]["id"]])[:1])
        answers.append(answer)
    assert result["status"] == "COMMITTED"
    menu = result["state"]["menu"]
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=CASTER, controller_mode="LOCAL_AUTO")
        real = combat.controller

        class EndTurnController:
            def choose_primary_action(self, context):
                end = next(c for c in context.legal_candidates if c.kind.value == "END_TURN")
                return ManualControllerAdapter(lambda _context: (end.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = EndTurnController()
        advancing_with_ai = True
    end_answers = []
    for _ in range(12):
        advancing_with_ai = auto_turn and menu["actor_id"] == CASTER
        before = combat._load_session(mid).engine.state.model_dump(mode="json")
        cid = menu["end_turn"]
        result = send(cid, menu, end_answers)
        if result["status"] == "REACTION_REQUIRED":
            if result["reaction"]["context"]["reaction_source_id"] == "choice:needle.rewrite_the_disaster":
                break
            end_answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
            continue
        menu = result["state"]["menu"]
        end_answers = []
    assert result["status"] == "REACTION_REQUIRED"
    assert advancing_with_ai == auto_turn
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.rewrite_the_disaster"
    assert prompt["reaction"].lower() == "rewrite the disaster"
    assert prompt["context"]["reactor_id"] == reactor
    names, _ = table._names_for(mid)
    for text in ("Rewrite the Disaster", names[PLAYER], "DEX saving throw", "Lava Flow", "observed d20:"):
        assert text in prompt["moment"]
    # fix/prompt-ui (round22 merge f9685b35) omits descriptions repeating the label.
    assert prompt["choice"]["options"] == [
        {"id": str(value), "label": f"Natural {value}: replace the observed d20 with {value}",
         "description": ""}
        for value in (1, 20)]
    assert prompt["choice"]["allow_decline"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send(cid, menu, end_answers)["reaction"] == prompt
    answer = {**prompt["context"], "selection": selection}
    if natural is not None:
        answer["option_ids"] = [str(natural)]
    result = send(cid, menu, [*end_answers, answer])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rewritten = [e for e in loaded.engine.events if e.event_type == "D20_REWRITTEN"]
    assert len(rewritten) == (1 if selection == "USE" else 0)
    if rewritten:
        assert rewritten[0].payload["result"]["natural_result"] == natural
    actor = loaded.engine.state.actors[reactor]
    assert actor.resources["resource:core.qi"] == (18 if selection == "USE" else 30)
    assert actor.resources.get("resource:named.heaven_s_notice", 0) == (2 if selection == "USE" else 0)
    assert actor.reaction_available == (selection == "DECLINE")
    assert loaded.engine._active_intent is None
    assert not getattr(loaded.engine, '_active_turn_advancing', False)
    assert not hasattr(loaded.engine, "_reaction_trigger")
    assert loaded.mechanical.replay()["status"] == "PASS"
