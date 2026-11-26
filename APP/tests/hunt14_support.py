"""Public synthetic table fixtures reproducing hunt14's seeded path probes."""
import json
import zipfile
from pathlib import Path

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
IDS = ["11111111", "22222222", "33333333", "44444444"]
ME, ALLY, FOE, OTHER = ["actor:factory." + key for key in IDS]
CTE = "tianxia.path.body_refining.feature.core_tempering_expression"
VOICE = "tianxia.path.body_refining.feature.iron_voice"
FIST = "tianxia.path.body_refining.feature.iron_fist"
GUARD = "tianxia.path.body_refining.feature.stamina_guard"


def fight(tmp_path, *, seed=0, cl=17, pb=4, offturn=False, mantle=False):
    for index, pid in enumerate(IDS):
        mids = ([CTE, VOICE, FIST, GUARD] if offturn else [CTE, VOICE, FIST]) if index == 0 else ([FIST] if offturn else [])
        if mantle:
            mids = ["TAL_MAGMA_FURNACE_MANTLE"] if index == 0 else []
        doc = sheet(mids, primary="Qi" if mantle else "Stamina", cl=cl,
                    score=(18 if index == 0 else 30) if offturn else 14)
        doc["identity"].update(display_name=["Tester", "Ally", "Target", "Other"][index], path="Body Refining")
        if index == 0:
            doc["identity"]["proficiency_bonus"] = pb
        path = tmp_path / "portable_characters" / pid
        path.mkdir(parents=True)
        with zipfile.ZipFile(path / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(IDS[0], {"mode": "ask"}, {"opportunity_attack"})
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    name = "offturn-yard" if offturn else "path-yard"
    combat.tabletop_maps.save({"map_id": name, "display_name": "Test Yard", "width_squares": 12,
        "height_squares": 8, "starts": {"team1": [[3,4], [3,6]], "team2": [[4,4], [4,6]]}})
    mid = combat.create_factory_match(project_ids=IDS[:2], opponent_actor_ids=[FOE, OTHER],
        control_modes={"actor:factory." + pid: "MANUAL" for pid in IDS}, arena_id="battlefield:map." + name,
        match_seed=("OFFTURN-FURNACE-" if offturn else "PATH-PROBE-") + str(seed), maximum_rounds=6)["match_id"]
    advance(table, mid, ME)
    return combat, table, mid


def act(table, mid, needle, target=None, *, selection="USE", option=None, auto=False, selected=False):
    state = table.state(mid)
    menu = state["menu"]
    original = table.combat.controller
    if auto and selected:
        from combat.gate4_adapters import ManualControllerAdapter
        engine = table.combat._load_session(mid).engine
        chosen = next(c for c in engine.legal_candidates() if
                      (c.kind.value == "END_TURN" if needle == "end" else needle in c.source_definition_id)
                      and (target is None or target in c.target_ids))
        class SelectedController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(original, name)
        table.combat.controller = SelectedController()
    if auto:
        call = lambda answers: table.auto_step(mid, state["last_sequence"], answers)
    else:
        if needle == "end":
            cid = menu["end_turn"]
        else:
            group = next(g for g in menu["actions"] if needle in g["source_definition_id"])
            cid = next(o["candidate_id"] for o in group["options"] if target is None or target in o["target_ids"])
        call = lambda answers: table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
    try:
        answers, prompts = [], []
        for _ in range(20):
            result = call(answers)
            if result["status"] != "REACTION_REQUIRED":
                assert result["status"] == "COMMITTED", result
                return prompts
            prompt = result["reaction"]
            from tests.iron_fist_support import IRON_FIST_DAMAGE_TYPE, automatic_answer
            if prompt["context"]["reaction_source_id"] == IRON_FIST_DAMAGE_TYPE:  # L45: answered, not one of this test's prompts
                answers.append(automatic_answer(prompt))
                continue
            prompts.append(prompt)
            answer = {**prompt["context"], "selection": selection}
            if prompt.get("choice") and selection == "USE":
                options = prompt["choice"]["options"]
                answer["option_ids"] = [option or options[0]["id"]]
            answers.append(answer)
        raise AssertionError("Repeated prompt without commit")
    finally:
        table.combat.controller = original


def advance(table, mid, actor):
    for _ in range(20):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        act(table, mid, "end")
    raise AssertionError("Turn did not advance")


def reload(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine
