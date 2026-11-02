"""Hunt 26: real table requests, transactional choices and fresh-service reloads."""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT

ME = FACTORY_ACTOR_PREFIX + "fix26-player"
FOE = FACTORY_ACTOR_PREFIX + "fix26-foe"
GLAMER = "TAL_ILLUSION_OBSCURING_GLAMER"
EXPLOIT = "TAL_THE_HIDDEN_EYE_EXPLOIT_WEAKNESS"


def fight(tmp_path, talents, *, auto=False, foe_talents=(), skilled=False, foe_ac=14, legacy_choices=False):
    documents = [sheet(talents, cl=15, score=30, kit={"starting_kit": KIT}),
                 sheet(foe_talents, cl=15, kit={"starting_kit": KIT})]
    documents[1]["ability_scores_and_statistics"]["armor_class"]["base_value"] = foe_ac
    if skilled:
        for row in documents[0]["ability_scores_and_statistics"]["abilities"]:
            if row["ability"] in {"INT", "WIS"}:
                row.update(score=50, modifier=20)
    for pid, name, document in zip(("fix26-player", "fix26-foe"), ("You", "Enemy"), documents):
        document["identity"]["display_name"] = name
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    bundles = [compile_character(documents[0], actor_id=ME, reaction_plan={"ask": True}),
               compile_character(documents[1], actor_id=FOE)]
    if legacy_choices:
        for row in bundles[0]["typed_passives"]:
            row.pop("choice_owner", None)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "LOCAL_AUTO" if auto else "MANUAL", FOE: "LOCAL_AUTO"},
        match_seed="FIX26", display_name="Hunt 26 regression", maximum_rounds=10)["match_id"]
    if table.state(mid)["menu"]["actor_id"] == FOE:
        submit(combat, table, mid, table.state(mid)["menu"]["end_turn"], auto=True)
    assert table.state(mid)["menu"]["actor_id"] == ME
    return combat, table, mid


def candidate(table, mid, label, target=None):
    if not table.state(mid)["menu"].get("manual"):
        return next(c.candidate_id for c in table.combat._load_session(mid).engine.legal_candidates()
                    if c.display_name == label and (target is None or target in c.target_ids))
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
                if g["label"] == label for o in g["options"]
                if target is None or target in o.get("target_ids", []))


def attack_candidate(table, mid, target):
    if not table.state(mid)["menu"].get("manual"):
        return next(c.candidate_id for c in table.combat._load_session(mid).engine.legal_candidates()
                    if c.display_name.endswith(" attack") and target in c.target_ids)
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
                if g["label"].endswith(" attack") for o in g["options"] if target in o.get("target_ids", []))


def submit(combat, table, mid, cid, *, auto=False, answers=()):
    state = table.state(mid)
    menu = state["menu"]
    if not auto:
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
    real = combat.controller

    class SelectedAction:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = SelectedAction()
    try:
        return table.auto_step(mid, state["last_sequence"], list(answers))
    finally:
        combat.controller = real


def reload(combat, mid):
    engine = combat._load_session(mid).engine
    fresh = CombatService(ROOT, combat.userdata_root)._load_session(mid).engine
    assert fresh.state.model_dump(mode="json") == engine.state.model_dump(mode="json")
    assert not any(e.event_type == "PLUGIN_EXCEPTION" for e in fresh.events)
    return fresh


def end_turn(table, mid):
    return next(c.candidate_id for c in table.combat._load_session(mid).engine.legal_candidates()
                if c.kind.value == "END_TURN")


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("seer", [False, True])
def test_self_invisible_survives_commit_reload_and_ai_attack(tmp_path, auto, seer):
    combat, table, mid = fight(tmp_path, [GLAMER, "tianxia.subpath.qi.ninpo_adept.feature.hidden_strike"], auto=auto,
                               foe_talents=["tianxia.path.spirit_awakening.feature.spiritual_sense"] if seer else [])
    cid = candidate(table, mid, "Obscuring Glamer: Invisible (1 CP)", ME)
    result = submit(combat, table, mid, cid, auto=auto)
    assert result["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert any(c.condition_id == "condition:typed.invisible" for c in engine.state.actors[ME].conditions.values())
    assert engine.state.actors[ME].resources["resource:core.qi"] == 29
    assert submit(combat, table, mid, end_turn(table, mid), auto=auto)["status"] == "COMMITTED"
    start = len(reload(combat, mid).events)
    assert submit(combat, table, mid, attack_candidate(table, mid, ME), auto=True)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    attacks = [e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED"]
    assert attacks and all(e.payload["mode"] == ("NORMAL" if seer else "DISADVANTAGE") for e in attacks)
    assert any(c.condition_id == "condition:typed.invisible" for c in engine.state.actors[ME].conditions.values())
    assert submit(combat, table, mid, end_turn(table, mid), auto=True)["status"] == "COMMITTED"
    start = len(reload(combat, mid).events)
    cid = attack_candidate(table, mid, FOE)
    before = reload(combat, mid).state.model_dump(mode="json")
    result = submit(combat, table, mid, cid, auto=auto)
    if not auto and not seer:
        # Printed Hidden Strike requires the player to choose an after-hit rider.
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert "Hidden Strike" in prompt["moment"] and "Enemy" in prompt["moment"]
        assert prompt["context"]["reactor_id"] == ME
        assert "sever" in {o["id"] for o in prompt["choice"]["options"]}
        assert reload(combat, mid).state.model_dump(mode="json") == before
        result = submit(combat, table, mid, cid, answers=[
            {**prompt["context"], "selection": "USE", "option_ids": ["sever"]}])
    assert result["status"] == "COMMITTED"
    engine = reload(combat, mid)
    attacks = [e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED"]
    assert attacks and attacks[0].payload["mode"] == ("NORMAL" if seer else "ADVANTAGE")
    triggered = any(e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("trigger") == "Hidden Strike"
                    for e in engine.events[start:])
    assert triggered is not seer
    assert not any(c.condition_id == "condition:typed.invisible" for c in engine.state.actors[ME].conditions.values())
