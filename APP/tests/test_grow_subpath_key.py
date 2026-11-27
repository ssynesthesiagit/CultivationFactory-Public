"""A committed Grow acquisition keeps the owning Path's key in cold combat."""
import json
from zipfile import ZipFile

from combat import table_advance
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, script, sheet

FOE = "actor:factory.grown-key-foe"
DAGGER_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou"}]}}

BODY = "tianxia.path.body_refining"
SPIRIT = "tianxia.path.spirit_awakening"
BONE = "tianxia.subpath.body.bone_monarch"
PID = "ba5eb011-0000-4000-8000-000000000003"


def test_cold_combat_uses_the_key_from_a_grown_subpaths_owning_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    owner = sheet([], cl=2, dc=11, primary="Resonance", kit=DAGGER_KIT)
    owner["identity"].update(path_id=SPIRIT, path="Spirit Awakening", key_ability="WIS", proficiency_bonus=2)
    owner["path_and_subpath"] = {"path_record_ids": [SPIRIT]}
    stats = owner["ability_scores_and_statistics"]
    for row in stats["abilities"]:
        if row["ability"] in ("WIS", "DEX"):
            row.update(score=12 if row["ability"] == "WIS" else 18,
                       modifier=1 if row["ability"] == "WIS" else 4)
    # Give the fixture a pool to test the delivered defensive roll; the subject
    # here is the origin of the modifier, not the initial provisioning of pools.
    stats["primary_resource"]["definitions"] = [{"name": "Stamina", "max": 12}]
    archive = tmp_path / "portable_characters" / PID / "current.zip"
    archive.parent.mkdir(parents=True)
    with ZipFile(archive, "w") as package:
        package.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(owner))

    store = ButtonStore(tmp_path / "tabletop_buttons")
    document = store.get(PID)
    document["advancement"] = table_advance.empty()
    document["advancement"]["levels"] = [{
        "cl": 3, "subpaths": {BODY: BONE},
        "add_path": {"path_id": BODY, "access": "gm", "source_id": "GM", "confirmed": True, "key_ability": "DEX"},
    }]
    store.root.mkdir(parents=True, exist_ok=True)
    (store.root / f"{PID}.json").write_text(json.dumps(document), encoding="utf-8")

    cold = CombatService(ROOT, tmp_path)
    table = TabletopService(cold, tmp_path)
    grown = cold._compile_factory(PID, actor_id=ME, reaction_plan={"ask": True})
    enemy = compile_character(sheet([], cl=3, key="INT", kit=DAGGER_KIT), actor_id=FOE)
    match = cold._finish_factory_match(
        [grown, enemy], [ME, FOE], {ME: "team:a", FOE: "team:b"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        cold.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="GROWN-KEY",
        display_name="Grown key", maximum_rounds=5,
    )["match_id"]

    def act(candidate_id, answers=()):
        return table.act(match, candidate_id, menu["decision_id"], menu["state_version"],
                         state["last_sequence"], list(answers))

    state = table.state(match)
    menu = state["menu"]
    if menu["actor_id"] != FOE:
        assert act(menu["end_turn"])["status"] == "COMMITTED"
        state = table.state(match)
        menu = state["menu"]
    assert menu["actor_id"] == FOE

    original = Gate4ControllerEngine._resolve_attack_spec

    def hit(engine, *args, **kwargs):
        script(engine, [19, *([3] * 10)])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", hit)
    current = cold._load_session(match).engine
    attack = next(c for c in current.legal_candidates() if c.target_ids == (ME,)
                  and c.display_name.endswith("(Dagger) attack"))
    answers = []
    for _ in range(8):
        result = act(attack.candidate_id, answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            break
        prompt = result["reaction"]
        selection = "USE" if "Bone Armor" in json.dumps(prompt) else "DECLINE"
        answers.append({**prompt["context"], "selection": selection})
    else:
        raise AssertionError("The attack never committed")
    assert any(answer["selection"] == "USE" for answer in answers)

    loaded = CombatService(ROOT, tmp_path)._load_session(match)
    assert loaded.mechanical.replay()["status"] == "PASS"
    engine = loaded.engine
    roll = next(roll for roll in engine.rolls if roll.actor_id == ME
                and roll.reason.endswith(f":{BONE}.feature.bone_armor"))
    assert roll.modifier == 4  # Body's DEX (not the primary Spirit Path's WIS +1)
