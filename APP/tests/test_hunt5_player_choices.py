"""Hunt 5's portable-sheet fixture: player decisions during another actor's action."""

import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.prepared_actions import CONDITION
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT

PLAYER = FACTORY_ACTOR_PREFIX + "h5-player"
FOE = FACTORY_ACTOR_PREFIX + "h5-foe"
FOCUS = "resource:core.martial_focus"


def fixture(tmp_path, mechanic):
    documents = [sheet([mechanic], cl=15, kit={"starting_kit": KIT}),
                 sheet([], cl=15, kit={"starting_kit": KIT})]
    for pid, document in zip(("h5-player", "h5-foe"), documents):
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    bundles = [compile_character(documents[0], actor_id=PLAYER, reaction_plan={"ask": True}),
               compile_character(documents[1], actor_id=FOE)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(
        bundles, [PLAYER, FOE], {PLAYER: "team:factory", FOE: "team:opponents"},
        {PLAYER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}, arena, [PLAYER], [FOE],
        control_modes={PLAYER: "MANUAL", FOE: "MANUAL"}, match_seed="H5-CHOICES",
        display_name="Off-turn choices", maximum_rounds=10)["match_id"]

    def act(cid, answers=()):
        menu = table.state(mid)["menu"]
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))

    menu = table.state(mid)["menu"]
    if menu["actor_id"] == FOE:
        assert act(menu["end_turn"])["status"] == "COMMITTED"
    if "COUNTERSTRIKE" in mechanic:
        group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == "Counterstrike")
        cid = group["options"][0]["candidate_id"]
        result = act(cid)
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        option = next(o["id"] for o in prompt["choice"]["options"] if "targets you" in o["label"])
        assert act(cid, [{**prompt["context"], "selection": "USE", "option_ids": [option]}])["status"] == "COMMITTED"
    assert act(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    menu = table.state(mid)["menu"]
    assert menu["actor_id"] == FOE
    cid = next(o["candidate_id"] for g in menu["actions"] for o in g["options"]
               if PLAYER in o.get("target_ids", []) and (o.get("expected_damage") or 0) > 0)
    real = combat.controller

    class AttackController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = AttackController()
    return combat, table, mid, cid, act


@pytest.mark.parametrize("mechanic,source", [
    ("TAL_FENCING_FOOTWORK", "choice:needle.footwork"),
    ("RETRIBUTION_BASE_COUNTERSTRIKE", "ready:retribution.counterstrike"),
])
@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_player_off_turn_choice_preview_commit_reload_replay(tmp_path, mechanic, source, auto_turn, selection):
    combat, table, mid, cid, act = fixture(tmp_path, mechanic)
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")

    def send(answers=()):
        return table.auto_step(mid, 0, list(answers)) if auto_turn else act(cid, answers)

    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == source
    if "FOOTWORK" in mechanic:
        assert prompt["reaction"] == "Footwork"
    else:
        assert prompt["reaction"].startswith("Counterstrike (")
    assert send()["reaction"]["context"] == prompt["context"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": selection, "option_ids": []}
    if prompt.get("choice") and selection == "USE":
        answer["option_ids"] = [next(o["id"] for o in prompt["choice"]["options"] if "Stay put" in o["label"])]
    assert send([answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[PLAYER]
    if "FOOTWORK" in mechanic:
        assert actor.resources[FOCUS] == before["actors"][PLAYER]["resources"][FOCUS] - (selection == "USE")
        assert actor.reaction_available
    else:
        attacks = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == PLAYER]
        assert len(attacks) == (selection == "USE")
        if selection == "DECLINE":
            assert actor.reaction_available
            assert any(c.condition_id == CONDITION for c in actor.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("mechanic", ["TAL_FENCING_FOOTWORK", "RETRIBUTION_BASE_COUNTERSTRIKE"])
@pytest.mark.parametrize("auto_turn", [False, True])
def test_ai_owned_choices_remain_automatic(tmp_path, mechanic, auto_turn):
    combat, table, mid, cid, act = fixture(tmp_path, mechanic)
    combat.set_controller_mode(mid, actor_id=PLAYER, controller_mode="LOCAL_AUTO")
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    result = table.auto_step(mid, 0) if auto_turn else act(cid)
    assert result["status"] == "COMMITTED"
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"
