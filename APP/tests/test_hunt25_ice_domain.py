"""Hunt 25 seed 23: real table transactions across the failing Domain step."""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT

DOMAIN = "TAL_ICE_ICE_DOMAIN_PALACE_OF_WRITTEN_WINTER"
ME, ALLY, FOE, FOE2 = ["actor:factory.h25" + name for name in ("owner", "ally", "foe", "foe2")]


def arena(tmp_path, *, manual=True, ask=True):
    ids = [ME, ALLY, FOE, FOE2]
    docs = [sheet([DOMAIN], cl=20, kit={"starting_kit": KIT})] + [
        sheet([], cl=20, kit={"starting_kit": KIT}) for _ in range(3)]
    for actor, doc, name in zip(ids, docs, ("You", "Ally", "Enemy", "Enemy Two")):
        doc["identity"]["display_name"] = name
        folder = tmp_path / "portable_characters" / actor.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    bundles = [compile_character(doc, actor_id=actor, reaction_plan={"ask": ask} if actor == ME else None)
               for actor, doc in zip(ids, docs)]
    mid = combat._finish_factory_match(
        bundles, ids, {ME: "team:factory", ALLY: "team:factory", FOE: "team:opponents", FOE2: "team:opponents"},
        {ME: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 6}, FOE2: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME, ALLY], [FOE, FOE2],
        control_modes={ME: "MANUAL" if manual else "LOCAL_AUTO"}, match_seed="H25-FOCUS-23",
        maximum_rounds=2, display_name="Hunt25 Ice Domain")["match_id"]
    return combat, mid


@pytest.mark.parametrize(("manual", "create"), [(True, True), (True, False), (False, True)])
def test_domain_lattice_commit_reload(tmp_path, manual, create):
    combat, mid = arena(tmp_path, manual=manual)
    table = TabletopService(combat, tmp_path)
    cast = False
    lattice_prompts = 0
    responses = 0
    linked = []
    for step in range(90):
        state = table.state(mid)
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result:
            break
        menu = state["menu"]
        cid = menu.get("end_turn")
        if menu["actor_id"] == ME:
            candidates = engine.legal_candidates()
            cid = next(c.candidate_id for c in candidates if c.kind.value == "END_TURN")
            if not cast:
                options = [c for c in candidates if DOMAIN in c.source_definition_id]
                cid = next((c.candidate_id for c in options if ME in c.target_ids), options[0].candidate_id)
                cast = True
            else:
                cid = next((c.candidate_id for c in candidates if ".weapon." in c.source_definition_id
                            and FOE in c.target_ids), cid)
        before = engine.state.model_dump(mode="json")
        event_start = len(engine.events)
        answers = []
        # Drive the same primary actions on AI turns, through its normal adapter.
        auto_owner = not manual and menu["actor_id"] == ME
        if auto_owner:
            from combat.gate4_adapters import ManualControllerAdapter
            real = combat.controller

            class Controller:
                def choose_primary_action(self, context):
                    return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)

                def __getattr__(self, name):
                    return getattr(real, name)

            combat.controller = Controller()
        for attempt in range(30):
            result = (table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
                      if menu.get("manual") else table.auto_step(mid, state["last_sequence"], answers))
            if result["status"] != "REACTION_REQUIRED":
                break
            prompt = result["reaction"]
            assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
            source = prompt["context"]["reaction_source_id"]
            is_lattice = source == "choice:needle.domain_lattice"
            if is_lattice:
                # Assert the text returned to the table, rather than plug-in constants.
                assert "Ice Domain" in prompt["reaction"]
                assert prompt["affected"] in prompt["moment"]
                for text in ("5-foot ice space", "Shatter Space", "marked creature", "Dexterity saving throw",
                             "falls Prone", "half damage", "mark the creature again",
                             "No Action or resource cost", "ends when your Ice Domain ends"):
                    assert text in prompt["moment"]
                label = prompt["choice"]["options"][0]["label"]
                for text in ("5-foot ice space", prompt["affected"], "Shatter Space", "marked creature",
                             "damage", "Prone", "No Action or resource cost", "ends when your Ice Domain ends"):
                    assert text in label
                assert prompt["choice"]["allow_decline"]
            lattice_prompts += is_lattice
            responses += source == "choice:needle.fracture_response"
            answer = {**prompt["context"], "selection": "USE" if create or not is_lattice else "DECLINE"}
            if prompt.get("choice") and answer["selection"] == "USE":
                answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
            assert answer not in answers
            answers.append(answer)
        else:
            pytest.fail("30 prompts without a table commit")
        assert result["status"] == "COMMITTED", result
        loaded = combat._load_session(mid)
        expected = loaded.engine.state.model_dump(mode="json")
        fresh = CombatService(ROOT, tmp_path)._load_session(mid)
        assert fresh.engine.state.model_dump(mode="json") == expected
        assert fresh.mechanical.replay()["status"] == "PASS"
        for event in loaded.engine.events[event_start:]:
            if event.event_type == "ZONE_CREATED" and event.payload["zone"]["trigger_profile"].get("ends_with"):
                zone = event.payload["zone"]
                linked.append(zone)
                assert zone["trigger_profile"]["lattice_space"]
                assert zone["trigger_profile"]["ends_with"] in expected["zones"]
        if auto_owner:
            combat.controller = real
    assert cast
    if manual:
        assert responses >= 1
        assert lattice_prompts >= 1
        assert bool(linked) == create
    else:
        assert lattice_prompts == 0  # AI chooses automatically, even with Ask me enabled.
        assert linked
