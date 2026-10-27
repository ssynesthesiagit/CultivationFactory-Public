"""Hunt 8: real hazard/save choices across table pause, commit and fresh reload."""

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_auto_martial import SPEAR_KIT

PLAYER, CASTER, ALLY = ("actor:factory.h8-" + name for name in ("player", "caster", "ally"))
FOOTWORK = "TAL_FENCING_FOOTWORK"
FATE = "TAL_FATE_REWRITE_THE_DISASTER"
LAMP = "tianxia.talent.life.soul_lamp_continuity"


def fight(tmp_path, player_talents, *, ally_talents=(), caster_talents=(), seed="H5-TURN-START"):
    ids = [PLAYER, CASTER, ALLY]
    docs = [sheet(list(talents), cl=15, dc=20) for talents in (player_talents, caster_talents, ally_talents)]
    for doc, name in zip(docs, ("H8 Player", "H8 Caster", "H8 Ally")):
        doc["identity"]["display_name"] = name
    if LAMP in ally_talents:
        docs[2]["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1
        docs[1] = sheet(list(caster_talents), cl=15, dc=20, kit=SPEAR_KIT)
        docs[1]["identity"]["display_name"] = "H8 Caster"
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True} if aid != CASTER else None)
               for doc, aid in zip(docs, ids)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids, {aid: "team:opponents" if aid == CASTER else "team:factory" for aid in ids},
        {PLAYER: {"x": 3, "y": 6}, CASTER: {"x": 4, "y": 6}, ALLY: {"x": 3, "y": 5}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [PLAYER, ALLY], [CASTER],
        control_modes={aid: "MANUAL" for aid in ids}, match_seed=seed,
        display_name="Hunt8 regression", maximum_rounds=20)["match_id"]
    return combat, table, mid


def send(table, mid, state, cid=None, answers=(), *, auto=False):
    if auto:
        return table.auto_step(mid, state["last_sequence"], list(answers))
    menu = state["menu"]
    return table.act(mid, cid or menu["end_turn"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], list(answers))


def end_turn_ai(combat, mid, actor):
    """Use the real AI table transport with a deterministic end-turn policy."""
    combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
    real = combat.controller

    class EndTurnController:
        def choose_primary_action(self, context):
            end = next(c for c in context.legal_candidates if c.kind.value == "END_TURN")
            return ManualControllerAdapter(lambda _context: (end.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = EndTurnController()


def cast_lava(combat, table, mid, *, caster=CASTER):
    state = table.state(mid)
    for _ in range(3):
        if state["menu"]["actor_id"] == caster:
            break
        result = send(table, mid, state)
        assert result["status"] == "COMMITTED"
        state = result["state"]
    group = next(g for g in state["menu"]["actions"] if "Lava Flow" in g["label"])
    cid = next(o["candidate_id"] for o in group["options"] if o.get("destination") == {"x": 3, "y": 6})
    answers = []
    for _ in range(10):
        result = send(table, mid, state, cid, answers)
        if result["status"] == "COMMITTED":
            return result["state"]
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt.get("choice") and not prompt["choice"].get("allow_decline"):
            answer.update(selection="USE", option_ids=[prompt["choice"]["options"][0]["id"]])
        answers.append(answer)
    pytest.fail("Lava Flow did not commit")


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_footwork_turn_start_hazard_prompt_commit_reload(tmp_path, auto_turn, selection):
    combat, table, mid = fight(tmp_path, [FOOTWORK], caster_talents=["TAL_MAGMA_LAVA_FLOW"])
    state = cast_lava(combat, table, mid)
    if auto_turn:
        end_turn_ai(combat, mid, CASTER)
        state = table.state(mid)
    for _ in range(3):
        before = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json")
        result = send(table, mid, state, auto=auto_turn and state["menu"]["actor_id"] == CASTER)
        if result["status"] == "REACTION_REQUIRED":
            break
        assert result["status"] == "COMMITTED"
        state = result["state"]
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == PLAYER
    for text in ("Footwork", "H8 Player", "Lava Flow", "Dexterity save"):
        assert text in prompt["moment"]
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before
    auto = auto_turn and state["menu"]["actor_id"] == CASTER
    assert send(table, mid, state, auto=auto)["reaction"] == prompt
    answer = {**prompt["context"], "selection": selection}
    if selection == "USE":
        answer["option_ids"] = prompt["choice"]["preferred"][:1]
    result = send(table, mid, state, answers=[answer], auto=auto)
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    saves = [e for e in loaded.engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == PLAYER
             and e.source_definition_id.endswith("TAL_MAGMA_LAVA_FLOW")]
    assert saves[-1].payload["mode"] == ("ADVANTAGE" if selection == "USE" else "NORMAL")
    assert loaded.engine.state.actors[PLAYER].resources["resource:core.martial_focus"] == (0 if selection == "USE" else 1)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
def test_allied_hazard_still_offers_footwork_at_turn_start(tmp_path, auto_turn):
    combat, table, mid = fight(tmp_path, [FOOTWORK], ally_talents=["TAL_MAGMA_LAVA_FLOW"])
    state = cast_lava(combat, table, mid, caster=ALLY)
    if auto_turn:
        for actor in (ALLY, CASTER):
            end_turn_ai(combat, mid, actor)
        state = table.state(mid)
    for _ in range(3):
        auto = auto_turn and state["menu"]["actor_id"] != PLAYER
        result = send(table, mid, state, auto=auto)
        if result["status"] == "REACTION_REQUIRED":
            break
        assert result["status"] == "COMMITTED"
        state = result["state"]
    assert result["status"] == "REACTION_REQUIRED" and auto == auto_turn
    prompt = result["reaction"]
    assert "Footwork" in prompt["moment"] and "Lava Flow" in prompt["moment"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": prompt["choice"]["preferred"][:1]}
    assert send(table, mid, state, answers=[answer], auto=auto)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    saves = [e for e in loaded.engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == PLAYER
             and e.source_definition_id.endswith("TAL_MAGMA_LAVA_FLOW")]
    assert saves[-1].payload["mode"] == "ADVANTAGE"
    assert loaded.engine.state.actors[PLAYER].resources["resource:core.martial_focus"] == 0
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
def test_ai_footwork_owner_decides_without_prompt_at_turn_start(tmp_path, auto_turn):
    combat, table, mid = fight(tmp_path, [FOOTWORK], caster_talents=["TAL_MAGMA_LAVA_FLOW"])
    state = cast_lava(combat, table, mid)
    combat.set_controller_mode(mid, actor_id=PLAYER, controller_mode="LOCAL_AUTO")
    if auto_turn:
        end_turn_ai(combat, mid, CASTER)
    state = table.state(mid)
    for _ in range(3):
        result = send(table, mid, state, auto=auto_turn and state["menu"]["actor_id"] == CASTER)
        assert result["status"] == "COMMITTED"
        state = result["state"]
        if state["menu"]["actor_id"] == PLAYER:
            break
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    saves = [e for e in loaded.engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == PLAYER
             and e.source_definition_id.endswith("TAL_MAGMA_LAVA_FLOW")]
    # Preserve the existing AI policy: save Footwork is optional and auto-declined.
    assert saves[-1].payload["mode"] == "NORMAL"
    assert loaded.engine.state.actors[PLAYER].resources["resource:core.martial_focus"] == 1
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("natural", [1, 20, None])
def test_disaster_turn_start_notice_once_commit_reload(tmp_path, auto_turn, natural):
    combat, table, mid = fight(tmp_path, [FATE], caster_talents=["TAL_MAGMA_LAVA_FLOW"])
    state = cast_lava(combat, table, mid)
    if auto_turn:
        end_turn_ai(combat, mid, CASTER)
        state = table.state(mid)
    for _ in range(3):
        before = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json")
        auto = auto_turn and state["menu"]["actor_id"] == CASTER
        result = send(table, mid, state, auto=auto)
        if result["status"] == "REACTION_REQUIRED":
            break
        assert result["status"] == "COMMITTED"
        state = result["state"]
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert "Rewrite the Disaster" in prompt["moment"] and "Lava Flow" in prompt["moment"]
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE" if natural else "DECLINE"}
    if natural:
        answer["option_ids"] = [str(natural)]
    assert send(table, mid, state, answers=[answer], auto=auto)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert_notice(loaded, used=natural is not None)


def assert_notice(loaded, *, used=True):
    actor = loaded.engine.state.actors[PLAYER]
    assert actor.resources["resource:named.heaven_s_notice"] == (2 if used else 0)
    assert actor.resources["resource:core.qi"] == (18 if used else 30)
    gains = [e for e in loaded.engine.events if e.event_type == "RESOURCE_GAINED" and e.actor_id == PLAYER
             and e.source_definition_id == FATE]
    assert len(gains) == (1 if used else 0)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
def test_ai_disaster_start_save_grants_notice_once(tmp_path, auto_turn):
    combat, table, mid = fight(tmp_path, [FATE], caster_talents=["TAL_MAGMA_LAVA_FLOW"])
    state = cast_lava(combat, table, mid)
    combat.set_controller_mode(mid, actor_id=PLAYER, controller_mode="LOCAL_AUTO")
    if auto_turn:
        end_turn_ai(combat, mid, CASTER)
    state = table.state(mid)
    for _ in range(3):
        result = send(table, mid, state, auto=auto_turn and state["menu"]["actor_id"] == CASTER)
        assert result["status"] == "COMMITTED"
        state = result["state"]
        if state["menu"]["actor_id"] == PLAYER:
            break
    assert_notice(CombatService(ROOT, tmp_path)._load_session(mid))


def expire_lamp(combat, table, mid, *, auto_turn=False, ai_owner=False):
    """Kill a lamp owner with table weapon attacks, accept its lamp, wait its real deadline."""
    state = table.state(mid)
    waiting = False
    for _ in range(100):
        loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
        lamp = any(c.data.get("lamp") for c in loaded.engine.state.actors[ALLY].conditions.values())
        if lamp and not waiting:
            waiting = True
            if ai_owner:
                end_turn_ai(combat, mid, PLAYER)
            if auto_turn:
                for actor in (CASTER, ALLY):
                    end_turn_ai(combat, mid, actor)
            state = table.state(mid)
        cid = None
        if state["menu"]["actor_id"] == CASTER and not waiting:
            attacks = [o for g in state["menu"]["actions"] if ".weapon." in g["source_definition_id"]
                       and "#" not in g["source_definition_id"] for o in g["options"] if ALLY in o["target_ids"]]
            if attacks:
                cid = attacks[0]["candidate_id"]
        answers = []
        auto = waiting and ((auto_turn and state["menu"]["actor_id"] != PLAYER)
                            or (ai_owner and state["menu"]["actor_id"] == PLAYER))
        for _ in range(10):
            result = send(table, mid, state, cid, answers, auto=auto)
            if result["status"] == "COMMITTED":
                break
            prompt = result["reaction"]
            if "Rewrite the Disaster" in prompt["moment"] and "CON saving throw" in prompt["moment"]:
                return state, answers, result, auto
            answer = {**prompt["context"], "selection": "DECLINE"}
            if "Soul-Lamp Continuity" in prompt["moment"]:
                answer.update(selection="USE", option_ids=[prompt["choice"]["options"][0]["id"]])
            answers.append(answer)
        assert result["status"] == "COMMITTED"
        state = result["state"]
        loaded = combat._load_session(mid)
        if any(e.event_type == "SAVE_ROLLED" and e.source_definition_id == "reaction:soul_lamp_continuity"
               for e in loaded.engine.events):
            return state, [], result, auto
    pytest.fail("Soul-Lamp never reached its deadline")


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("natural", [1, 20, None])
def test_disaster_nested_lamp_save_notice_once(tmp_path, auto_turn, natural):
    combat, table, mid = fight(tmp_path, [FATE], ally_talents=[LAMP], seed="H8-LAMP")
    state, answers, result, auto = expire_lamp(combat, table, mid, auto_turn=auto_turn)
    assert result["status"] == "REACTION_REQUIRED"
    assert auto == auto_turn
    before = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json")
    prompt = result["reaction"]
    assert send(table, mid, state, answers=answers, auto=auto)["reaction"] == prompt
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE" if natural else "DECLINE"}
    if natural:
        answer["option_ids"] = [str(natural)]
    assert send(table, mid, state, answers=[*answers, answer], auto=auto)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert_notice(loaded, used=natural is not None)
    rewrites = [e for e in loaded.engine.events if e.event_type == "D20_REWRITTEN"]
    assert len(rewrites) == (1 if natural else 0)
    if natural:
        assert rewrites[0].payload["result"]["natural_result"] == natural
        assert loaded.engine.state.actors[ALLY].current_hp == (1 if natural == 20 else 0)


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("use", [False, True])
def test_lamp_save_rewrite_prompt_names_source_commit_reload(tmp_path, auto_turn, use):
    combat, table, mid = fight(tmp_path, [FATE], ally_talents=[LAMP], seed="H8-LAMP")
    state, answers, result, auto = expire_lamp(combat, table, mid, auto_turn=auto_turn)
    assert result["status"] == "REACTION_REQUIRED" and auto == auto_turn
    prompt = result["reaction"]
    for text in ("Rewrite the Disaster", "H8 Ally", "CON saving throw", "Soul-Lamp Continuity", "observed d20:"):
        assert text in prompt["moment"]
    assert "Saving Throw (observed" not in prompt["moment"]
    before = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json")
    assert send(table, mid, state, answers=answers, auto=auto)["reaction"] == prompt
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE" if use else "DECLINE"}
    if use:
        answer["option_ids"] = ["20"]
    assert send(table, mid, state, answers=[*answers, answer], auto=auto)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert_notice(loaded, used=use)
    assert not loaded.engine.__dict__.get("_d20_frames")
    assert loaded.engine.state.actors[ALLY].current_hp == (1 if use else 0)


@pytest.mark.parametrize("auto_turn", [False, True])
def test_ai_lamp_save_rewrite_uses_dc_and_source_without_prompt(tmp_path, auto_turn):
    combat, table, mid = fight(tmp_path, [FATE], ally_talents=[LAMP], seed="H8-LAMP")
    _, _, result, _ = expire_lamp(combat, table, mid, auto_turn=auto_turn, ai_owner=True)
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert_notice(loaded)
    assert loaded.engine.state.actors[ALLY].current_hp == 1
    rewritten = [e for e in loaded.engine.events if e.event_type == "D20_REWRITTEN"]
    assert len(rewritten) == 1 and rewritten[0].payload["result"]["natural_result"] == 20
    assert not loaded.engine.__dict__.get("_d20_frames")
