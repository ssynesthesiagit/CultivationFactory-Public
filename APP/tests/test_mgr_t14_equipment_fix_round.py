"""Public setup and repeated-rest regressions from the Equipment Sol review."""
import httpx
import pytest

from app.api import create_app
from app.core import Settings
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from tests.async_support import run_asgi
from tests.h1_support import ROOT
from tests.test_mgr_t14_equipment_review import install
from tests.test_mgr_t14_fitted_armor import ACTOR, PROJECT, LAMELLAR, LEATHER, sheet, fight, support
from tests.test_mgr_t14_armor_defenses import critical_action, strike, HELMET_POOL
from tests.test_mgr_t14_armor_consumers import finish


def choose(combat, operation, **parameters):
    menu = combat.character_preparation_options(PROJECT)
    option = next(c for c in menu["commands"] if c["operation"] == operation and
                  all(c["parameters"].get(k) == v for k, v in parameters.items()))
    return combat.character_preparation(PROJECT, operation, parameters=option["parameters"],
                                        expected_revision=menu["state"]["revision"])


@pytest.mark.parametrize("kind", ["helmet", "mask", "armored hood", "equivalent"])
def test_public_head_protection_setup_reaches_helmet_prompt_and_cold_fight(tmp_path, kind):
    doc = sheet(["helmet_discipline", "sleep_in_armor"])
    install(tmp_path, doc)  # No hand-authored head_protection profile.
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    url = f"/api/tabletop/characters/{PROJECT}/preparation"
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            headers = {"X-Foundry-Token": (await client.get("/api/session")).json()["token"]}
            menu = (await client.get(url)).json()
            option = next(c for c in menu["commands"] if c["operation"] == "armor.head_protection" and
                          c["parameters"] == {"item_key": LAMELLAR, "kind": kind})
            assert "Helmet Discipline" in option["label"] and "Lamellar" in option["label"]
            for invalid in ({"item_key": "invented", "kind": kind},
                            {"item_key": LEATHER, "kind": kind},
                            {"item_key": LAMELLAR, "kind": {}},
                            {"item_key": [], "kind": kind},
                            {"item_key": LAMELLAR, "kind": "lantern hood"}):
                reply = await client.post(url, headers=headers, json={"operation": option["operation"],
                    "parameters": invalid, "expected_revision": menu["state"]["revision"]})
                assert reply.status_code == 422, reply.text
            reply = await client.post(url, headers=headers, json={"operation": option["operation"],
                "parameters": option["parameters"], "expected_revision": menu["state"]["revision"]})
            assert reply.status_code == 200, reply.text
            assert reply.json()["state"]["armor"]["head_protection"] == {"armor_key": LAMELLAR, "kind": kind}
    run_asgi(exercise())
    combat, table, mid = fight(tmp_path, doc, prepare=critical_action)
    prompts, cold, rolled = strike(combat, table, mid)
    assert len(prompts) == 1 and not rolled.payload["critical"]
    assert cold.state.actors[ACTOR].resources[HELMET_POOL] == 0
    subject = next(b for b in cold.typed_bundle_documents if b["actor_id"] == ACTOR)["armor_subject"]
    assert subject["head_protection_key"] == LAMELLAR and subject["head_protection_kind"] == kind
    finish(combat, table, mid)
    choose(CombatService(ROOT, tmp_path), "armor.head_protection", item_key=LAMELLAR, kind="none")
    combat, table, mid = fight(tmp_path, doc, prepare=critical_action)
    subject = next(b for b in support._reload(tmp_path, mid).typed_bundle_documents if b["actor_id"] == ACTOR)["armor_subject"]
    assert not subject.get("head_protection_key")


def test_saved_equipment_sphere_grant_prepares_and_seals_fitted_suit(tmp_path):
    doc = sheet()
    doc["spheres_and_talents"]["sphere_record_ids"] = []
    doc["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
    install(tmp_path, doc)
    buttons = ButtonStore(tmp_path / "tabletop_buttons")
    sphere = "tianxia.sphere.equipment"
    buttons.save_granted_spheres(PROJECT, [sphere], {sphere})
    combat = CombatService(ROOT, tmp_path)
    choose(combat, "armor.fit.start", item_key=LAMELLAR)
    state = choose(combat, "time.advance", observation="fitting")
    assert state["armor"]["ready"] == 1
    cold = CombatService(ROOT, tmp_path)
    match = cold.create_factory_match(project_ids=[PROJECT], match_seed="SOL-GRANTED-EQUIPMENT", maximum_rounds=1)
    engine = support._reload(tmp_path, match["match_id"])
    subject = next(b for b in engine.typed_bundle_documents if b["actor_id"] == ACTOR)["armor_subject"]
    assert subject["ready"] == 1 and subject["fitted_key"] == LAMELLAR
    # Revoking a saved grant cannot project the old fitted benefit.
    buttons.save_granted_spheres(PROJECT, [], {sphere})
    assert not any(c["operation"] == "armor.fit.start" for c in cold.character_preparation_options(PROJECT)["commands"])


def test_two_rest_cycles_menu_waits_remaining_cooldown_and_resets_helmet(tmp_path):
    doc = sheet(["helmet_discipline", "sleep_in_armor"])
    doc["equipment"][0]["head_protection"] = {"armor_key": LAMELLAR, "kind": "helmet"}
    install(tmp_path, doc)
    combat = CombatService(ROOT, tmp_path)
    for generation in (1, 2):
        # Use Helmet Discipline between rests through native damage + cold reload.
        combat, table, mid = fight(tmp_path, doc, prepare=critical_action)
        prompts, cold, rolled = strike(combat, table, mid)
        assert prompts and not rolled.payload["critical"]
        assert cold.state.actors[ACTOR].resources[HELMET_POOL] == 0
        finish(combat, table, mid)
        combat = CombatService(ROOT, tmp_path)
        if generation == 2:
            menu = combat.character_preparation_options(PROJECT)
            assert not any(c["operation"] == "rest.start" for c in menu["commands"])
            wait = next(c for c in menu["commands"] if c["operation"] == "time.advance" and c["parameters"].get("observation") == "unobserved")
            assert "next long rest" in wait["label"] and wait["parameters"]["seconds"] == 57600
            # Some waiting has already happened: offer precisely the remainder.
            combat.character_preparation(PROJECT, "time.advance", parameters={"seconds": 600}, expected_revision=menu["state"]["revision"])
            menu = combat.character_preparation_options(PROJECT)
            wait = next(c for c in menu["commands"] if c["operation"] == "time.advance" and c["parameters"].get("observation") == "unobserved")
            assert wait["parameters"]["seconds"] == 57000
            choose(combat, "time.advance", observation="unobserved")
        choose(combat, "rest.start", kind="long_rest")
        state = choose(combat, "time.advance", observation="sleep")
        assert state["rest_generation"] == generation
    combat, table, mid = fight(tmp_path, doc, prepare=critical_action)
    assert support._reload(tmp_path, mid).state.actors[ACTOR].resources[HELMET_POOL] == 1
