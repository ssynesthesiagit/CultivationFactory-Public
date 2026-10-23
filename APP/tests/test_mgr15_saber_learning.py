"""Saber-Line Method: native table acquisition, durable choices and weapon use.

Synthetic starting sheets contain no Method, selection or successful adjudication.
All new learning and GM facts enter through the public table selectors/API.
No live model, owner data, or fabricated success effects are used.
"""
import copy
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import httpx
import pytest

from app.api import create_app
from app.core import Settings
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService
from tests.async_support import run_asgi
from tests.h1_support import sheet
from tests.hunt15_support import act, turn

ROOT = Path(__file__).resolve().parents[1]
PID = "abadcafe-0000-4000-8000-000000000015"
ACTOR = "actor:factory." + PID
METHOD = "SABERS_BASE_SABER_LINE_METHOD"
SPHERE = "tianxia.sphere.sabers"
DAO = "tianxia.mortal.weapon.dao"
DUAN = "tianxia.mortal.weapon.duan_dao"
BUTTERFLY = "tianxia.mortal.weapon.hu_die_dao"
AMBIGUOUS = "tianxia.mortal.weapon.guandao_yanyuedao"
SPEAR = "tianxia.mortal.weapon.qiang"


def install(root, document):
    """A synthetic installed-sheet input to native table advancement, no receipts."""
    target = root / "portable_characters" / PID / "current.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))


def services(root):
    combat = CombatService(ROOT, root)
    table = TabletopService(combat, root)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return combat, table


def baseline(items=(DAO, DUAN, BUTTERFLY, SPEAR), path="tianxia.path.qi_cultivation"):
    doc = sheet([], cl=10, kit={"starting_kit": {"items": [{"item_id": i} for i in items]}})
    doc["identity"]["display_name"] = "Saber Student"
    doc["path_and_subpath"] = {"path_record_ids": [path], "path_record_id": path}
    return doc


def learned(root, document=None):
    install(root, document or baseline())
    combat, table = services(root)
    assert table.learning_options(PID) == []
    options = table.advancement(PID)
    assert next(o for o in options["spheres"] if o["id"] == SPHERE)["legal"]
    table.add_advancement(PID, "sphere", SPHERE)
    assert METHOD in combat._factory_owner_sheet(PID)["spheres_and_talents"]["automatic_sphere_component_record_ids"]
    return combat, table


def commit(table, mid, source):
    """Send the action and answer each reaction it asks (an Opportunity Attack, or the Forward Cut step) through
    the table, the way a player does, until the action commits. Same rule as tests/test_auto92_sabers._answer."""
    answers = []
    for _ in range(12):
        result = act(table, mid, source, answers)
        if result["status"] != "REACTION_REQUIRED":
            return result
        prompt = result["reaction"]
        chosen = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])][:1]
        if prompt["context"]["reaction_source_id"] == "reaction:core.stamina_guard":
            # The defender declines its Stamina Guard: DECLINE is legal with spend 0 and avoids a resource spend.
            answers.append({**prompt["context"], "selection": "DECLINE", "option_ids": []})
            continue
        answers.append({**prompt["context"], "selection": "USE" if chosen or not prompt.get("choice") else "DECLINE",
                        "option_ids": chosen})
    raise AssertionError("too many reactions before the action committed")


def weapons(combat):
    bundle = compile_character(combat._factory_owner_sheet(PID), actor_id=ACTOR)
    return {a["parameters"]["typed"]["source"]: a["parameters"]["typed"]
            for a in bundle["action_catalog"] if ".weapon." in a["source_definition_id"]
            and "#" not in a["source_definition_id"] and a["parameters"].get("typed", {}).get("weapon")}


@pytest.mark.parametrize("chosen", [DAO, DUAN, BUTTERFLY])
def test_public_learning_choice_survives_cold_reopen_gear_change_and_recompile(tmp_path, chosen):
    combat, table = learned(tmp_path)
    selector, = table.learning_options(PID)
    assert {DAO, DUAN, BUTTERFLY} <= {o["item_id"] for o in selector["options"]}
    assert not any(weapons(combat)[i]["proficient"] for i in (DAO, DUAN, BUTTERFLY))
    table.choose_learning(PID, selector["source_id"], chosen)
    combat, table = services(tmp_path)
    selected, = table.learning_options(PID)
    assert selected["selected"]["item_id"] == chosen
    before = copy.deepcopy(selected["selected"])
    for carried in ((SPEAR,), (BUTTERFLY, DUAN, DAO, SPEAR)):
        install(tmp_path, baseline(carried))
        combat, table = services(tmp_path)
        assert table.learning_options(PID)[0]["selected"] == before
        got = weapons(combat)
        for item in set(carried) & {DAO, DUAN, BUTTERFLY}:
            assert got[item]["proficient"] == (item == chosen)
        assert not got[SPEAR]["proficient"]
    with pytest.raises(TabletopError, match="already chosen"):
        table.choose_learning(PID, METHOD, DAO)


def test_gm_can_correct_an_unsealed_sabers_ruling_to_another_sphere(tmp_path):
    """Finding: a GM ruling of Sabers on a non-printed blade vanished from the correction list, so a mistaken
    classification could not be fixed through the Grow workflow. It must stay correctable until a choice seals it."""
    combat, table = learned(tmp_path, baseline((AMBIGUOUS,)))
    table.choose_learning(PID, METHOD, AMBIGUOUS, gm_sphere="sabers", gm=True)
    selector, = table.learning_options(PID)
    assert AMBIGUOUS in {o["item_id"] for o in selector["options"]}
    assert AMBIGUOUS in {o["item_id"] for o in selector["ambiguous"]}
    assert not any(o["item_id"] == DAO for o in selector["ambiguous"]), "printed examples are never reclassified"
    table.choose_learning(PID, METHOD, AMBIGUOUS, gm_sphere="axes", gm=True)
    combat, table = services(tmp_path)
    assert weapons(combat)[AMBIGUOUS]["saber_profile"] == "axes"
    selector, = table.learning_options(PID)
    assert AMBIGUOUS not in {o["item_id"] for o in selector["options"]}
    assert AMBIGUOUS in {o["item_id"] for o in selector["ambiguous"]}
    table.choose_learning(PID, METHOD, AMBIGUOUS, gm_sphere="sabers", gm=True)
    table.choose_learning(PID, METHOD, AMBIGUOUS)
    selector, = table.learning_options(PID)
    assert AMBIGUOUS not in {o["item_id"] for o in selector["ambiguous"]}, "a learned weapon seals its ruling"


def test_grow_correction_round_trip_in_the_browser_module():
    """Finding: the Grow UI round trip for correcting a ruling was not exercised. Runs the real grow.js through
    a DOM double (tests/grow_learning.test.mjs), with the GM's ruling and the posted body checked."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    result = subprocess.run([node, "--test", str(ROOT / "tests/grow_learning.test.mjs")],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_proficiency_is_idempotent_and_never_grants_an_extra_talent(tmp_path):
    combat, table = learned(tmp_path, baseline(path="tianxia.path.body_refining"))
    before = copy.deepcopy(combat._factory_owner_sheet(PID)["spheres_and_talents"])
    bonus = weapons(combat)[DAO]["numbers"]["attack_bonus"]
    table.choose_learning(PID, METHOD, DAO)
    combat, _ = services(tmp_path)
    assert weapons(combat)[DAO]["numbers"]["attack_bonus"] == bonus
    assert combat._factory_owner_sheet(PID)["spheres_and_talents"] == before


def test_ambiguous_identity_requires_explicit_gm_decision_and_cannot_be_reclassified_after_choice(tmp_path):
    combat, table = learned(tmp_path, baseline((AMBIGUOUS,)))
    assert weapons(combat)[AMBIGUOUS]["saber_profile"] == "unknown"
    with pytest.raises(TabletopError):
        table.choose_learning(PID, METHOD, AMBIGUOUS)
    with pytest.raises(TabletopError) as error:
        table.choose_learning(PID, METHOD, AMBIGUOUS, gm_sphere="sabers")
    assert error.value.status_code == 403
    table.choose_learning(PID, METHOD, AMBIGUOUS, gm_sphere="axes", gm=True)
    combat, table = services(tmp_path)
    assert weapons(combat)[AMBIGUOUS]["saber_profile"] == "axes"
    with pytest.raises(TabletopError):
        table.choose_learning(PID, METHOD, AMBIGUOUS)
    table.choose_learning(PID, METHOD, AMBIGUOUS, gm_sphere="sabers", gm=True)
    table.choose_learning(PID, METHOD, AMBIGUOUS)
    combat, table = services(tmp_path)
    assert weapons(combat)[AMBIGUOUS]["saber_profile"] == "sabers"
    assert weapons(combat)[AMBIGUOUS]["proficient"]
    ruling, = combat._factory_owner_sheet(PID)["weapon_rulings"]
    assert ruling["principal"]["provider"] in {"posix_effective_uid", "windows_process_token"}
    with pytest.raises(TabletopError):
        table.choose_learning(PID, METHOD, AMBIGUOUS, gm_sphere="axes", gm=True)


@pytest.mark.parametrize("weapon,approved", [(DAO, False), (DUAN, False), (BUTTERFLY, False), (AMBIGUOUS, True)])
def test_acquired_method_and_weapon_delivery_commit_reload_and_replay(tmp_path, weapon, approved):
    combat, table = learned(tmp_path, baseline((weapon,)))
    if approved:
        table.choose_learning(PID, METHOD, weapon, gm_sphere="sabers", gm=True)
    table.choose_learning(PID, METHOD, weapon)
    # Real rules-checked talent acquisition, no manually installed success flags.
    table.add_advancement(PID, "talent", "tianxia.talent.sabers.forward_cut")
    combat, table = services(tmp_path)
    bundle = compile_character(combat._factory_owner_sheet(PID), actor_id=ACTOR)
    mid = combat._finish_factory_match([bundle], [ACTOR, AN], {ACTOR: "team:factory", AN: "team:opponents"},
        {ACTOR: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ACTOR], [AN],
        control_modes={ACTOR: "MANUAL", AN: "MANUAL"}, match_seed="SABER-LEARNING",
        display_name="Saber learning regression", maximum_rounds=10)["match_id"]
    turn(table, mid, ACTOR)
    assert commit(table, mid, "Forward Cut")["status"] == "COMMITTED"
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ACTOR for e in cold.engine.events)
    assert cold.verify()["status"] == "PASS"
    assert cold.mechanical.replay()["status"] == "PASS"


def test_unknown_named_blade_withholds_talent_and_nonowner_cannot_choose(tmp_path):
    install(tmp_path, baseline((AMBIGUOUS,)))
    combat, table = services(tmp_path)
    with pytest.raises(TabletopError):
        table.choose_learning(PID, METHOD, DAO)
    combat, table = learned(tmp_path, baseline((AMBIGUOUS,)))
    table.add_advancement(PID, "talent", "tianxia.talent.sabers.forward_cut")
    from tests.test_mgr14_saber_method import _engine
    bundle = compile_character(combat._factory_owner_sheet(PID), actor_id="actor:factory.mgr_t14_saber_method")
    assert not any(c.display_name == "Forward Cut" for c in _engine(bundle).legal_candidates())


def test_http_learning_requires_local_session_token_and_explicit_gm_declaration(tmp_path):
    learned(tmp_path, baseline((AMBIGUOUS,)))
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            url = f"/api/tabletop/characters/{PID}/learning-choice"
            body = {"source_id": METHOD, "item_id": AMBIGUOUS, "gm_sphere": "sabers"}
            assert (await client.post(url, json=body)).status_code == 403
            token = (await client.get("/api/session")).json()["token"]
            headers = {"X-Foundry-Token": token}
            assert (await client.post(url, json=body, headers=headers)).status_code == 403
            assert (await client.post(url, json={**body, "gm": True}, headers=headers)).status_code == 200
            assert (await client.post(url, json={"source_id": METHOD, "item_id": AMBIGUOUS}, headers=headers)).status_code == 200
    run_asgi(check())
    combat, table = services(tmp_path)
    assert table.learning_options(PID)[0]["selected"]["item_id"] == AMBIGUOUS


def test_printed_method_record_is_the_reviewed_typed_record():
    """The Method's typed record (ids, action economy, range, cost, rider count and the reviewed source fingerprint)
    is what the table relies on. Asserted on typed fields only: no prose is hashed, so public redaction cannot change it."""
    typed = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"][METHOD]
    assert typed["mechanic_id"] == METHOD and typed["sphere_id"] == SPHERE
    assert typed["activation"]["economy"] == "passive" and typed["range"]["kind"] == "self"
    assert typed["cost"] == [] and typed["effects"] == []
    assert len(typed["riders"]) == 3
    assert typed["source"]["text_sha256"] == "ded67f0e36f0822c0598e156ad1e07c1a506d981ef4d3d4083f78b2b9217e5de"
    assert METHOD in json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())


def test_non_method_character_keeps_the_pre_method_saber_eligibility(monkeypatch):
    """MGR-T15 finding 1: a non-printed "dao" (Guandao Yanyuedao) on a character without the Method keeps
    Sabers-talent eligibility (the name rule that predates the Method), instead of losing it to the printed-only rule."""
    from types import SimpleNamespace
    from combat.ext import saber_learning
    guandao = SimpleNamespace(display_name="Guandao Yanyuedao", parameters={"typed": {"weapon": {"dice": "1d10"}, "source": AMBIGUOUS}})
    spear = SimpleNamespace(display_name="Qiang", parameters={"typed": {"weapon": {"dice": "1d8"}, "source": SPEAR}})
    assert saber_learning.saber_action(guandao) is True
    assert saber_learning.saber_action(spear) is False
    # An owner's sealed profile stays authoritative: a sealed "unknown" never falls back to the name.
    sealed = SimpleNamespace(display_name="Guandao Yanyuedao", parameters={"typed": {"weapon": {"dice": "1d10"}, "source": AMBIGUOUS, "saber_profile": "unknown"}})
    assert saber_learning.saber_action(sealed) is False


def test_owner_without_a_choice_sees_a_notice_on_the_learning_row(monkeypatch):
    """MGR-T15 finding 2: an owner who has not chosen loses the proficiency silently. The learning row must say so."""
    from combat.ext import saber_learning
    monkeypatch.setattr(saber_learning, "owns", lambda sheet: True)
    rows = saber_learning.learning_options({"learning_choices": [], "weapon_rulings": []})
    assert rows and "no proficiency" in rows[0]["notice"]
    chosen = saber_learning.learning_options({"learning_choices": [{"source_id": METHOD, "item_id": DAO, "item_sha256": saber_learning.weapon_stamp(DAO)}], "weapon_rulings": []})
    assert chosen[0]["notice"] == ""
