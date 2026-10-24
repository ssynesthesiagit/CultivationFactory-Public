"""Real seeded Quick Builds: constructors and pinned source loaders are untouched."""
import json
import time
import sys
import os
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest

from app.api import create_app
from app.core import Settings, FoundryError
from ai_provider.secrets import InMemorySecretStore
from character_creation import CharacterCreationExecutionService
from product_bootstrap.service import ProductBootstrapService


@pytest.fixture(scope="module")
def recipe_builds(tmp_path_factory):
    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path_factory.mktemp("recipes"))
    # Keep temporary snapshots outside the data tree that they copy.
    scratch = settings.data_dir.parent / "recipe-tmp"
    scratch.mkdir(parents=True)
    old_tmpdir, old_tempdir = os.environ.get("TMPDIR"), tempfile.tempdir
    os.environ["TMPDIR"] = str(scratch)
    tempfile.tempdir = str(scratch)
    ProductBootstrapService(settings).run()

    def no_ai(*args, **kwargs):
        raise AssertionError("Seeded Quick Builds must not call an AI transport")

    app = create_app(settings, ai_transport=no_ai, ai_secret_store=InMemorySecretStore())
    app.state.ai_provider.configure(
        enabled=True, provider_id="deepseek", endpoint="https://api.deepseek.com/chat/completions",
        model="deepseek-v4-flash", thinking_mode="enabled", max_output_tokens=1024,
        timeout_seconds=30, data_sharing_acknowledged=True, acknowledged_by="test",
    )
    guard = {"active": True}

    def no_browser(event, args):
        if not guard["active"] or event != "subprocess.Popen":
            return
        command = str(args[:2]).lower()
        if any(word in command for word in ("exact_consumer_harness.py", "run_command6.py", "chromium", "google-chrome", "firefox")):
            raise FoundryError("SOL58_BROWSER_BLOCKED", "Lead must verify the browser consumer outside the sandbox")

    sys.addaudithook(no_browser)
    batch = app.state.quick_builds.submit(
        items=[{"route": "seeded", "seed": seed, "concept": "A Body Refining fighter who protects allies."}
               for seed in ("Q59-CL5-P0-V1", "Q59-CL5-P0-V1", "Q59-different")],
        target_cl=15, finalize=False,
    )
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        batch = app.state.quick_builds._read(batch["batch_id"])
        if all(row["status"] in {"ready", "failed", "needs_review", "interrupted"} for row in batch["items"]):
            break
        time.sleep(.1)
    try:
        assert all(row["status"] in {"ready", "needs_review"} for row in batch["items"]), batch["items"]
        for item in batch["items"]:
            run = app.state.character_creation.get(item["run_id"])
            if item["status"] == "needs_review":
                assert {b["code"] for b in run["blockers"]} == {"SOL58_BROWSER_BLOCKED"}
                assert "SOL58_BROWSER_BLOCKED" in str(run["blockers"])
        yield app, batch["items"]
    finally:
        guard["active"] = False
        tempfile.tempdir = old_tempdir
        if old_tmpdir is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = old_tmpdir


def _recipes(service, run):
    """Reconstruct the persisted response using the production materializer."""
    response = json.loads(run["response"]["exact_response_text"])
    plan, intent, _ = service._normalize_and_materialize_response(run, response)
    service._materialize_constructed_arts(run, service.db, phase="test-reload", plan=plan)
    from character_creation.constructed_arts.records import constructed_art_contract
    result = {"forged_technique": [], "manual": [], "immortal_art": []}
    with service.db.connection() as conn:
        records = conn.execute("SELECT record_json FROM project_locked_records WHERE project_id=? ORDER BY record_id", (run["project_id"],)).fetchall()
    for row in records:
        contract = constructed_art_contract(json.loads(row["record_json"]))
        if contract and contract["kind"] in result:
            result[contract["kind"]].append(contract)
    return result


def _semantic(value):
    """Keep all recipe mechanics and printed source IDs; omit provenance."""
    if isinstance(value, dict):
        return {key: _semantic(v) for key, v in value.items()
                if key not in {"construction", "pack_hash", "rule_id", "owner_project_id"}}
    if isinstance(value, list):
        return [_semantic(v) for v in value]
    if isinstance(value, str) and value.startswith(("tianxia.constructed.", "tianxia.manual.collection.")):
        return "constructed-provenance-id"
    return value


def test_seeded_quick_build_recipes(recipe_builds):
    app, items = recipe_builds
    service = app.state.character_creation
    runs = [service.get(item["run_id"]) for item in items]
    recipes = [_recipes(service, run) for run in runs]
    assert all(recipes[0][family] and recipes[1][family] for family in recipes[0])
    for family in recipes[0]:
        # Records are sorted by project-specific identity, so compare the
        # recipes as a multiset instead of comparing their incidental order.
        first = sorted(json.dumps(_semantic(x), sort_keys=True) for x in recipes[0][family])
        second = sorted(json.dumps(_semantic(x), sort_keys=True) for x in recipes[1][family])
        assert first == second, family
    assert _semantic(recipes[0]) != _semantic(recipes[2])
    first_marker = runs[0]["request"]["server_owned_authority"]["manual_collection"]
    assert first_marker == runs[1]["request"]["server_owned_authority"]["manual_collection"]
    assert first_marker != runs[2]["request"]["server_owned_authority"]["manual_collection"]
    def identities(recipe):
        if isinstance(recipe, dict):
            return {value for value in recipe.values() if isinstance(value, str)
                    and value.startswith(("tianxia.constructed.", "tianxia.manual.collection."))} | set().union(
                        *(identities(value) for value in recipe.values()))
        if isinstance(recipe, list):
            return set().union(*(identities(value) for value in recipe))
        return set()
    assert identities(recipes[0])
    assert identities(recipes[0]).isdisjoint(identities(recipes[1]))


def test_persisted_recipe_reload_is_byte_identical(recipe_builds):
    app, items = recipe_builds
    service = app.state.character_creation
    run = service.get(items[0]["run_id"])
    before = _recipes(service, run)
    # Read both the request and response afresh from durable storage.
    after = _recipes(service, service.get(run["run_id"]))
    assert before == after
    marker = run["request"]["server_owned_authority"]["manual_collection"]
    rebuilt_request = service._complete_request(
        run["project_id"], execution_mode=run["execution_mode"],
        idempotency_key=run["idempotency_key"], controller_route=run["request"]["controller_route"],
        manual_collection_nonce=marker["nonce"],
    )
    assert rebuilt_request["server_owned_authority"]["manual_collection"] == marker


def test_unseeded_real_recipes_match_legacy_constructor_bytes(recipe_builds):
    """Compare real constructors against the pre-fix seed formulas, byte for byte."""
    from app.core import canonical_json, sha256_json
    from character_creation.constructed_arts.forged_technique import construct_forged_technique
    from character_creation.constructed_arts.forging_authority import load_forging_authority
    from character_creation.constructed_arts.immortal_art import construct_immortal_art, load_immortal_art_authority
    from character_creation.constructed_arts.manual import construct_lineage_manual, roll_manual_collection_count, MANUAL_COLLECTION_POLICY_ID
    from recorded_art_authority import RECORDED_ART_CONSTRUCTION_KIND

    app, items = recipe_builds
    service = app.state.character_creation
    created = app.state.character_builder.create_project(
        working_name="Legacy recipe check", concept="A Body Refining fighter who protects allies.",
        source_reference=None, target_cl=15, power_band="rival/boss", creation_mode="quick",
        generation_route="ai_bootstrap", ability_scores={}, selections={}, autogen_seed=None,
    )
    app.state.character_builder.commit_normal_first_cycle_catalog_choices(created["project_id"])
    run = deepcopy(service.get(items[0]["run_id"]))
    plan, intent, _ = service._normalize_and_materialize_response(run, json.loads(run["response"]["exact_response_text"]))
    project = service._project(created["project_id"])
    assert not any(lock["field"] == "character_creation.autogen_seed" for lock in project["user_locks"])
    nonce = "legacy-server-nonce-for-unseeded-project"
    seed = "cg1.manual.collection." + sha256_json({"policy_id": MANUAL_COLLECTION_POLICY_ID, "nonce": nonce})
    unseeded_request = service._complete_request(
        created["project_id"], controller_route=run["request"]["controller_route"], manual_collection_nonce=nonce,
    )
    assert unseeded_request["server_owned_authority"]["manual_collection"]["seed"] == seed
    run["project_id"] = created["project_id"]
    marker = run["request"]["server_owned_authority"]["manual_collection"]
    marker.update(nonce=nonce, seed=seed, roll=roll_manual_collection_count(15, seed=seed))
    document = intent.as_dict()
    document["acquisition_intent"].pop("manual_collection", None)
    rows = [r for r in plan["stage2_proposal"]["choices"]
            if r["kind"] not in {"training_source_access", RECORDED_ART_CONSTRUCTION_KIND, "forged_technique_creation", "immortal_art_creation"}]
    records = service._locked_records_for_run(run)
    service._add_delegated_path_records(
        run, records, service._delegated_path_ids_from_canonical_intent(intent), db=service.db, store=service.projects,
    )
    bundles, _, _ = service._manual_collection_constructions(run, project, document, rows, records, 15, intent_hash=intent.intent_hash)
    assert bundles
    for index, bundle in enumerate(bundles):
        request = bundle["manual"]["construction"]["request"]
        assert request["seed"] == seed
        assert bundle["manual"]["collection"]["collection_id"] == f"tianxia.manual.collection.{sha256_json({'seed': seed, 'index': index})[:24]}"
        assert canonical_json(bundle) == canonical_json(construct_lineage_manual(request))
    forged = service._forged_technique_constructions(run, project, document, rows, records, 15, intent_hash=intent.intent_hash)
    assert forged
    for index, (technique, _) in enumerate(forged):
        request = deepcopy(technique["construction"]["request"])
        legacy = f"{run['project_id']}:{intent.intent_hash}:forged_technique:{index}"
        assert request["seed"] == legacy
        request["seed"] = legacy
        rebuilt = construct_forged_technique(load_forging_authority(service.db.settings.root_dir), request,
                                            generator_version=technique["construction"].get("generator_version", 1))
        assert canonical_json(technique) == canonical_json(rebuilt)
    arts = service._immortal_art_constructions(run, project, document, rows, records, 15, intent_hash=intent.intent_hash)
    assert arts
    for index, (art, _) in enumerate(arts):
        request = deepcopy(art["construction"]["request"])
        legacy = f"{run['project_id']}:{intent.intent_hash}:immortal_art:{index}"
        assert request["seed"] == legacy
        request["seed"] = legacy
        assert canonical_json(art) == canonical_json(construct_immortal_art(load_immortal_art_authority(service.db.settings.root_dir), request))


def test_persisted_pre_fix_recipe_hash_is_unchanged():
    run = {"request": {"server_owned_authority": {"manual_collection": {"nonce": "historical-nonce" * 3}}}}
    assert CharacterCreationExecutionService._constructed_recipe_intent_hash(run, {"acquisition_intent": {"manual_collection": {}}}, "original-hash") == "original-hash"


def test_unseeded_recipe_keeps_exact_legacy_seed():
    for kind in ("manual", "manual_collection", "forged_technique", "immortal_art"):
        legacy = f"project-one:original-hash:{kind}:0"
        assert CharacterCreationExecutionService._constructed_recipe_seed({}, "original-hash", kind, legacy_seed=legacy) == legacy
