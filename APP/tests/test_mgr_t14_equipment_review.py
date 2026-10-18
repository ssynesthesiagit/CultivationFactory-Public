"""Review regressions through public preparation and journalled native combat.

ASGI only: isolated portable characters and fake controller selections; no
browser, live service, model or embedding requests in the default test path.
"""
import json
import zipfile

import httpx
import pytest

from app.api import create_app
from app.core import Settings
from combat.gate5_service import CombatService
from combat.preparation import PreparationStore
from combat.ext.equipment_armor import CIRCUIT, PADDED_ROUND_FLAG
from combat.tabletop import ButtonStore, normalize_map, to_battlefield
from factory_authoring import owner_items as O
from tests.async_support import run_asgi
from tests.h1_support import ROOT
from tests.test_mgr_t14_fitted_armor import ACTOR, PROJECT, LAMELLAR, LEATHER, sheet, fight, fit, support, command
from tests.test_mgr_t14_armor_defenses import brute_sheet, DAMAGE, damage_action


def install(root, doc):
    path = root / "portable_characters" / PROJECT / "current.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO", "MODEL"])
def test_public_preparation_named_choices_reach_every_control_mode(tmp_path, mode):
    doc = sheet(["armor_ease", "hidden_plates", "sleep_in_armor", "helmet_discipline"])
    doc["equipment"][0]["head_protection"] = {"armor_key": LAMELLAR, "kind": "helmet"}
    install(tmp_path, doc)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    url = f"/api/tabletop/characters/{PROJECT}/preparation"
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            token = (await client.get("/api/session")).json()["token"]
            headers = {"X-Foundry-Token": token}
            response = await client.get(url)
            assert response.status_code == 200, response.text
            menu = response.json()
            suits = [c for c in menu["commands"] if c["operation"] == "armor.fit.start"]
            assert {c["parameters"]["item_key"] for c in suits} == {LAMELLAR, LEATHER}
            assert all("armor" in c["label"] and "10 minutes" in c["label"] for c in suits)
            assert {c["parameters"]["category"] for c in menu["commands"] if c["operation"] == "armor.ease.choose"} == {"light", "medium"}
            assert len([c for c in menu["commands"] if c["operation"] == "armor.conceal"]) == 5
            async def choose(operation, **parameters):
                nonlocal menu
                option = next(c for c in menu["commands"] if c["operation"] == operation and
                              all(c["parameters"].get(k) == v for k, v in parameters.items()))
                reply = await client.post(url, headers=headers, json={"operation": operation,
                    "parameters": option["parameters"], "expected_revision": menu["state"]["revision"]})
                assert reply.status_code == 200, reply.text
                menu = reply.json()
            await choose("armor.fit.start", item_key=LAMELLAR)
            await choose("time.advance", observation="fitting")
            await choose("armor.ease.choose", category="medium")
            await choose("armor.conceal", disguise="travel robes")
            await choose("rest.start", kind="long_rest")
            await choose("time.advance", observation="sleep")
            assert menu["state"]["armor"]["ready"] == 1
            assert menu["state"]["rest_generation"] == 1
            stale = await client.post(url, headers=headers, json={"operation": "rest.start",
                "parameters": {}, "expected_revision": 0})
            assert stale.status_code == 422
    run_asgi(exercise())
    cold = CombatService(ROOT, tmp_path)
    menu = cold.character_preparation_options(PROJECT)
    assert menu["state"]["armor"]["disguise"] == "travel robes"
    assert cold.factory_prefight_options(PROJECT)["preparation"] == menu
    match = cold.create_factory_match(project_ids=[PROJECT], control_modes={ACTOR: "MANUAL" if mode == "MODEL" else mode},
        match_seed="REVIEW-PUBLIC-" + mode, maximum_rounds=1)
    if mode == "MODEL":
        from combat.tabletop_service import TabletopService
        from tests.test_agent_seats import runner_for
        def no_inference(*args):
            raise AssertionError("Preparation and seat setup must not call a model")
        runner, _ = runner_for(tmp_path, TabletopService(cold, tmp_path), no_inference)
        runner.set_seat(match["match_id"], ACTOR, "MODEL", "fake")
        assert runner.seats(match["match_id"])[ACTOR]["control"] == "MODEL"
    engine = cold._load_session(match["match_id"]).engine
    subject = next(b for b in engine.typed_bundle_documents if b["actor_id"] == ACTOR)["armor_subject"]
    assert subject["ready"] == 1 and subject["fitted_key"] == LAMELLAR
    assert subject["ease_categories"] == ["medium"] and subject["disguise"] == "travel robes"
    assert engine.state.actors[ACTOR].resources["resource:equipment.helmet_discipline"] == 1


@pytest.mark.parametrize("case", ["given", "omitted"])
def test_preparation_uses_real_saved_fight_inventory(tmp_path, case):
    doc = sheet()
    install(tmp_path, doc)
    chassis = "tianxia.mortal.armor.beast_hide_harness"
    choices = O.armour_choices(chassis, "Spiritual", None, [])
    given = O.OwnerItemStore(tmp_path / "owner_items").give(PROJECT, {"kind": "armour", "chassis_id": chassis,
        "grade": "Spiritual", "material_id": choices["material_id"]})
    # Given armor is worn; the old kit's unworn Leather can be left behind.
    ButtonStore(tmp_path / "tabletop_buttons").save_left_behind(PROJECT, [LEATHER])
    combat = CombatService(ROOT, tmp_path)
    if case == "omitted":
        with pytest.raises(ValueError, match="source-qualified"):
            combat.character_preparation(PROJECT, "armor.fit.start", parameters={"item_key": LEATHER}, expected_revision=0)
        return
    state = combat.character_preparation(PROJECT, "armor.fit.start", parameters={"item_key": "given.0"}, expected_revision=0)
    state = combat.character_preparation(PROJECT, "time.advance", parameters={"seconds": 600, "observation": "fitting"}, expected_revision=state["revision"])
    assert state["armor"]["fitted_identity"] == given["item_uid"]
    assert state["armor"]["fitted_key"] == "treasure_armor"  # the same suit's worn alias
    match = combat.create_factory_match(project_ids=[PROJECT], match_seed="REVIEW-GIVEN", maximum_rounds=1)
    bundle = next(b for b in combat._load_session(match["match_id"]).engine.typed_bundle_documents if b["actor_id"] == ACTOR)
    assert bundle["armor_subject"]["fitted_key"] == "treasure_armor" and bundle["armor_subject"]["ready"] == 1
    engine = support._reload(tmp_path, match["match_id"])
    from combat.ext.armor_subject import fitted_ready
    assert fitted_ready(engine, engine.state.actors[ACTOR])
    assert LEATHER not in {i["key"] for i in bundle["carrying"]["items"]}


def test_local_auto_finishing_damage_cold_rest_uses_committed_health(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    from services.factory_dm_v0.gameplay.models import EngineError
    doc = sheet(["sleep_in_armor"])
    def fatal(bundle):
        damage_action(bundle)
        if bundle["actor_id"] == support.ATTACKER:
            next(a for a in bundle["action_catalog"] if a["source_definition_id"] == DAMAGE)["parameters"]["typed"]["effects"][0]["flat"] = 1000
            support._seal(bundle)
    combat, table, mid = fight(tmp_path, doc, prepare=fatal)
    real = combat.controller
    class FixedController:
        def choose_primary_action(self, context):
            selected = next((c for c in context.legal_candidates if c.source_definition_id == DAMAGE), None)
            if selected is None:
                selected = next(c for c in context.legal_candidates if c.kind == "END_TURN")
            return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = FixedController()
    for aid in (ACTOR, support.ATTACKER):
        combat.set_controller_mode(mid, actor_id=aid, controller_mode="LOCAL_AUTO")
    for _ in range(40):
        if combat._load_session(mid).engine.state.terminal_result:
            break
        assert combat.local_step(mid)["status"] == "COMMITTED"
    cold = support._reload(tmp_path, mid)
    assert cold.state.terminal_result and cold.state.actors[ACTOR].current_hp == 0
    # No manual/table commits after the Auto damage: a cold service must reject
    # rest using the final authoritative health receipt.
    with pytest.raises(EngineError, match="ACTOR_CANNOT_ACT"):
        command(tmp_path, doc, "rest.start", kind="long_rest")
    assert PreparationStore(tmp_path).read(ACTOR)["combat_hp"] == 0


@pytest.mark.parametrize("obstacle", ["surface", "object"])
@pytest.mark.parametrize("use_padded", [True, False])
def test_collision_combines_and_settles_exact_circuit_and_padded_defenses(tmp_path, obstacle, use_padded):
    doc = sheet(["padded_layers", "circuit_armor", "mountain_pattern_grand_shell"])
    fit(tmp_path, doc)
    arena = to_battlefield(normalize_map({"display_name": "Circuit collision yard", "width_squares": 12, "height_squares": 8,
        "walls": [{"shape": "rect", "points": [[5, 6], [6, 7]], "filled": True}] if obstacle == "surface" else [],
        "objects": [{"id": 1, "kind": "wall_section", "x": 5, "y": 6}] if obstacle == "object" else [],
        "starts": {"team1": [[4, 6]], "team2": [[3, 6]]}}))
    combat, table, mid = fight(tmp_path, doc, attacker_sheet=brute_sheet(), attacker_position=(3, 6),
                             defender_position=(4, 6), arena=arena)
    support._commit(combat, table, mid, "tianxia.talent.equipment.circuit_armor", actor=ACTOR)
    engine = combat._load_session(mid).engine
    assert any(c.condition_id == CIRCUIT for c in engine.state.actors[ACTOR].conditions.values())
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == support.ATTACKER and (a.parameters.get("typed") or {}).get("source") == "BRUTE_BASE_BRUTAL_SHOVE")
    def answer(prompt):
        ids = [o["id"] for o in prompt["choice"]["options"]]
        if "padded_layers" in prompt["context"]["reaction_source_id"]:
            return ["use"] if use_padded else None
        return ["push"] if "push" in ids else ids[:1]
    support._commit(combat, table, mid, source, answer=answer, max_steps=20)
    cold = support._reload(tmp_path, mid)
    target = cold.state.actors[ACTOR]
    packets = [e for e in support._packets(cold, source) if ACTOR in e.target_ids]
    packet = next(e for e in packets if "collision_with_object_or_surface" in e.payload.get("source_flags", []))
    roll = next(r for r in cold.rolls if r.reason == "HAMMER_IMPACT_COLLISION")
    pb = target.proficiency_bonus
    # With Padded accepted, Grand Shell steps aside. Otherwise its larger PB
    # wins the existing choose-one rule over Circuit's key modifier.
    reduction = 2 * pb + support.KEY_MODIFIER if use_padded else pb
    assert packet.payload["hp_damage"] == max(0, roll.total - reduction)
    assert (target.turn_flags.get(PADDED_ROUND_FLAG) == cold.state.round_number) is use_padded
    # Hammer also deals a separate follow-up packet. Assert each packet's exact
    # selection rather than mistaking that later legal use for collision reuse.
    reduction_sources = {"passive:Circuit Armor", "passive:Mountain-Pattern Grand Shell"}
    before_collision = [e.source_definition_id for e in cold.events if e.sequence < packet.sequence
                        and e.source_definition_id in reduction_sources]
    assert before_collision == ["passive:Circuit Armor" if use_padded else "passive:Mountain-Pattern Grand Shell"]
    follow_up = next(e for e in packets if e.sequence > packet.sequence)
    between_packets = [e.source_definition_id for e in cold.events if packet.sequence < e.sequence < follow_up.sequence
                       and e.source_definition_id in reduction_sources]
    assert between_packets == ["passive:Mountain-Pattern Grand Shell" if use_padded else "passive:Circuit Armor"]
    assert target.turn_flags.get("equipment_round_circuit") == cold.state.round_number
    assert target.turn_flags.get("equipment_round_grand_shell") == cold.state.round_number
    assert packet.payload["source_flags"] == ["collision_with_object_or_surface"]
    from combat.pending_damage import packet_scratch
    assert packet_scratch(cold) is None
