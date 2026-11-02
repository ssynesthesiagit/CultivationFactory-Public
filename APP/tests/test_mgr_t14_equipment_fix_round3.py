"""Public GET reconciliation must durably revoke fitting and stale revisions.

ASGI requests use isolated portable source sheets, never a live service/model.
"""
import httpx
import pytest

from app.api import create_app
from app.core import Settings
from combat.gate5_service import CombatService
from combat.preparation import PreparationStore
from tests.async_support import run_asgi
from tests.h1_support import ROOT
from tests.test_mgr_t14_equipment_review import install
from tests.test_mgr_t14_equipment_fix_round import choose
from tests.test_mgr_t14_fitted_armor import ACTOR, PROJECT, LAMELLAR, LEATHER, sheet, support


def preparation_app(root):
    app = create_app(Settings.from_env(ROOT, root))
    app.state.agent_seats.background = False
    return app


@pytest.mark.parametrize("receipt", ["fitted", "pending"])
def test_get_revocation_survives_source_restoration_and_cold_fight(tmp_path, receipt):
    doc = sheet()
    install(tmp_path, doc)
    combat = CombatService(ROOT, tmp_path)
    choose(combat, "armor.fit.start", item_key=LAMELLAR)
    if receipt == "fitted":
        choose(combat, "time.advance", observation="fitting")
    else:
        # Partly completed work must also be cancelled by lost proficiency.
        state = PreparationStore(tmp_path).read(ACTOR)
        combat.character_preparation(PROJECT, "time.advance",
            parameters={"seconds": 300, "observation": "fitting"}, expected_revision=state["revision"])
    doc["proficiencies"]["armor"] = ["light"]
    install(tmp_path, doc)
    app = preparation_app(tmp_path)
    async def inspect():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            reply = await client.get(f"/api/tabletop/characters/{PROJECT}/preparation")
            assert reply.status_code == 200, reply.text
            armor = reply.json()["state"]["armor"]
            assert not armor["fitted_key"] and not armor.get("pending")
    run_asgi(inspect())
    # No saving inspect command: only GET saw the loss of proficiency.
    doc["proficiencies"]["armor"] = ["medium", "light"]
    install(tmp_path, doc)
    cold = CombatService(ROOT, tmp_path)
    match = cold.create_factory_match(project_ids=[PROJECT], control_modes={ACTOR: "MANUAL"},
        match_seed="F3-GET-REVOKED-" + receipt, maximum_rounds=1)
    engine = support._reload(tmp_path, match["match_id"])
    subject = next(b for b in engine.typed_bundle_documents if b["actor_id"] == ACTOR)["armor_subject"]
    assert not subject["fitted_key"] and not subject["ready"]
    armor = PreparationStore(tmp_path).read(ACTOR)["armor"]
    assert not armor.get("pending"), "Cancelled fitting must not revive when training returns"
    assert not armor["fitted_key"] and not armor["ready"]


def test_get_reconciliation_invalidates_stale_commands_without_revision_churn(tmp_path):
    doc = sheet()
    install(tmp_path, doc)
    combat = CombatService(ROOT, tmp_path)
    choose(combat, "armor.fit.start", item_key=LAMELLAR)
    fitted = choose(combat, "time.advance", observation="fitting")
    doc["proficiencies"]["armor"] = ["light"]
    install(tmp_path, doc)
    app = preparation_app(tmp_path)
    url = f"/api/tabletop/characters/{PROJECT}/preparation"
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            token = (await client.get("/api/session")).json()["token"]
            headers = {"X-Foundry-Token": token}
            reply = await client.get(url)
            assert reply.status_code == 200, reply.text
            menu = reply.json()
            state = menu["state"]
            assert state["revision"] == fitted["revision"] + 1
            assert PreparationStore(tmp_path).read(ACTOR) == state
            assert state["elapsed_seconds"] == fitted["elapsed_seconds"]
            assert state["rest_generation"] == fitted["rest_generation"]
            again = await client.get(url)
            assert again.status_code == 200, again.text
            assert again.json() == menu, "Unchanged inspection must not invalidate another client"
            stale = await client.post(url, headers=headers, json={"operation": "armor.fit.start",
                "parameters": {"item_key": LEATHER}, "expected_revision": fitted["revision"]})
            assert stale.status_code == 422, stale.text
            assert "refresh" in stale.text
            assert PreparationStore(tmp_path).read(ACTOR) == state
            # The fresh revision still permits the complete legal light-suit option.
            assert any(c["operation"] == "armor.fit.start" and c["parameters"]["item_key"] == LEATHER
                       for c in menu["commands"])
            fresh = await client.post(url, headers=headers, json={"operation": "armor.fit.start",
                "parameters": {"item_key": LEATHER}, "expected_revision": state["revision"]})
            assert fresh.status_code == 200, fresh.text
            assert fresh.json()["state"]["armor"]["pending"]["key"] == LEATHER
    run_asgi(exercise())
