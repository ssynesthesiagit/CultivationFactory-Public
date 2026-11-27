"""Cold table reads of actual Path grants, new and pre-key-choice."""
import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.core import FoundryError, sha256_file
from combat import table_advance
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from path_keys import sheet_key

BODY = "tianxia.path.body_refining"
QI = "tianxia.path.qi_cultivation"
SPIRIT = "tianxia.path.spirit_awakening"
ROOT = Path(__file__).resolve().parents[1]
PID = "ba5eb011-0000-4000-8000-000000000002"


@pytest.mark.parametrize("granted,key", [(BODY, "CON"), (QI, "INT")])
def test_cold_table_load_persists_legacy_path_grant_key(tmp_path, granted, key):
    sheet = {
        "identity": {"path_id": SPIRIT, "key_ability": "WIS", "cultivation_level": 1, "proficiency_bonus": 2},
        "path_and_subpath": {"path_record_ids": [SPIRIT]},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": ability, "score": 12, "modifier": 1}
                          for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "hit_points": {"maximum": 9},
        },
    }
    package = tmp_path / "portable_characters" / PID / "current.zip"
    package.parent.mkdir(parents=True)
    with ZipFile(package, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))

    button_path = tmp_path / "tabletop_buttons" / f"{PID}.json"
    button_path.parent.mkdir()
    document = ButtonStore(button_path.parent).get(PID)
    document["advancement"] = table_advance.empty()
    document["advancement"]["levels"] = [
        {"cl": 2, "add_path": {"path_id": granted, "access": "gm", "source_id": "GM", "confirmed": True}}
    ]
    button_path.write_text(json.dumps(document), encoding="utf-8")

    cold = CombatService(ROOT, tmp_path)
    sheet = cold._factory_owner_sheet(PID)
    assert sheet_key(sheet) == "WIS"
    assert sheet_key(sheet, granted) == key
    saved = json.loads(button_path.read_text())
    assert saved["advancement"]["levels"][0]["add_path"]["key_ability"] == key

    stamp = button_path.stat().st_mtime_ns
    assert sheet_key(CombatService(ROOT, tmp_path)._factory_owner_sheet(PID), granted) == key
    assert button_path.stat().st_mtime_ns == stamp
    del saved["advancement"]["levels"][0]["add_path"]["key_ability"]
    button_path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(FoundryError) as error:
        CombatService(ROOT, tmp_path)._factory_owner_sheet(PID)
    assert error.value.code == "PATH_KEY_ABILITY_MISSING"


def test_creator_finalizes_dex_body_and_cold_table_loads_it(tmp_path, monkeypatch):
    from app.api import create_app
    from app.core import Settings
    from character_creation import production_release
    from character_creation.creative_controller import seeded_picker
    from gm_export import service as gm_export
    from product_bootstrap import service as bootstrap
    from projector import verification

    monkeypatch.setenv("TIANXIA_AUTO_TOKEN", "0")
    monkeypatch.setenv("TIANXIA_CONCEPT_EMBEDDINGS", "0")
    if os.environ.get("BODYKEY1_PORTABLE_E2E") == "1":
        monkeypatch.setenv("TIANXIA_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    else:
        # Keep package generation, audit, clean import and publication real.
        # Only the external GM consumer is simulated.
        consumer_zip = tmp_path / "synthetic_consumer.zip"
        with ZipFile(consumer_zip, "w") as archive:
            archive.writestr("index.html", "<title>Synthetic GM consumer</title>")
        consumer_hash = sha256_file(consumer_zip)
        monkeypatch.setattr(bootstrap, "GM_SCREEN_RELATIVE_PATH", consumer_zip)
        monkeypatch.setattr(bootstrap, "EXPECTED_GM_SCREEN_HASH", consumer_hash)
        monkeypatch.setattr(gm_export.GMCharacterExportService, "bundled_gm_zip", property(lambda self: consumer_zip))
        monkeypatch.setattr(gm_export, "GM_SCREEN_SHA256", consumer_hash)
        monkeypatch.setattr(production_release, "GM_SCREEN_SHA256", consumer_hash)

        run_tool = verification._run

        def run_without_browser(command, **kwargs):
            if Path(command[1]).name != "exact_consumer_harness.py":
                assert Path(command[1]).name != "run_command6.py"
                return run_tool(command, **kwargs)
            package = Path(command[command.index("--package") + 1])
            report = Path(command[command.index("--output") + 1])
            report.write_text(json.dumps({
                "status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
                "package_sha256": sha256_file(package),
                "semantic_hash": "test-browser-consumer",
            }), encoding="utf-8")
            return {"exit_code": 0}

        monkeypatch.setattr(verification, "_run", run_without_browser)
    settings = Settings.from_env(ROOT, tmp_path / "userdata")
    bootstrap.ProductBootstrapService(settings).run()

    def no_ai(*args, **kwargs):
        raise AssertionError("The deterministic creator must not call an AI transport")

    app = create_app(settings, ai_transport=no_ai)
    normal_choice = seeded_picker.choose_option

    def choose(seed, menu, **kwargs):
        if menu.step_kind in {"path_key_ability", "background_ability"}:
            return next(option.option_id for option in menu.options if option.choice_ids[:1] == ("DEX",))
        return normal_choice(seed, menu, **kwargs)

    monkeypatch.setattr(seeded_picker, "choose_option", choose)
    project = app.state.character_builder.create_project(
        working_name="Still Reed", concept="A nimble unarmored Body Refiner",
        target_cl=1, power_band="standard", source_reference=None,
        creation_mode="detailed", generation_route="ai_bootstrap",
        selections={"path_choice": [BODY], "background_choice": ["tianxia.background.abandoned_orphan"]},
        ability_scores={"STR": 15, "DEX": 15, "CON": 15, "INT": 8, "WIS": 8, "CHA": 8},
        autogen_seed="QB-AAA111",
    )
    pid = project["project_id"]
    app.state.character_builder.commit_normal_first_cycle_catalog_choices(pid)
    run = app.state.character_creation.start(
        pid, execution_mode="STANDARD_API", idempotency_key="body-key-dex",
        controller_route="DETERMINISTIC_CREATIVE_CONTROLLER",
    )
    assert run["status"] == "READY_FOR_REVIEW", run.get("diagnostics")
    result = app.state.character_creation.finalize(run["run_id"])
    assert result["status"] == "CLEAN_AND_FINALIZED", result.get("diagnostics")

    cold = CombatService(ROOT, settings.data_dir)
    path = cold.require_factory_character(pid)
    with ZipFile(path) as archive:
        model = json.loads(archive.read("Tianxia_GM_Character_Model_v2.json"))
    assert next(row for row in model["cultivation"]["paths"] if row["path_id"] == BODY)["key_ability"] == "DEX"
    sheet = cold._factory_owner_sheet(pid)
    assert sheet_key(sheet) == "DEX"
    stats = sheet["ability_scores_and_statistics"]
    assert next(row["modifier"] for row in stats["abilities"] if row["ability"] == "DEX") == 3
    assert stats["armor_class"]["base_value"] == 15
    actor = compile_character(sheet, actor_id="actor:factory.still-reed")["actor_template"]
    assert actor["armor_class"] == 15
    assert actor["maximum_hp"] == 14
    assert actor["saving_throws"]["CON"] == 2
    assert next(pool["maximum"] for pool in actor["resources"] if pool["resource_id"] == "resource:core.stamina") == 3
