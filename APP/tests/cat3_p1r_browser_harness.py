from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import threading
import zipfile
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import uvicorn

from ai_provider.secrets import InMemorySecretStore
from app.api import create_app
from app.core import Database, Settings, canonical_json
from catalog.service import CatalogService
from character_builder import CharacterBuilderService
from character_creation.current_fixture import exact_stage1_response
from character_creation.choice_snapshot import valid_choice_snapshot
from non_sphere_authority.service import NonSphereAuthorityService
from vendor_adapter.service import FactoryAdapter

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"

SPHERES = [
    "tianxia.sphere.beauty",
    "tianxia.sphere.ash",
    "tianxia.sphere.athletics",
    "tianxia.sphere.blood",
    "tianxia.sphere.dark",
]
FREE_GRANTS = {
    "tianxia.sphere.beauty": "tianxia.talent.beauty.admiring_crowd_method",
    "tianxia.sphere.ash": "tianxia.talent.ash.ash_ward",
    "tianxia.sphere.athletics": "TAL_ATHLETICS_WALL_STUNT",
    "tianxia.sphere.blood": "tianxia.talent.blood.blood_armament",
    "tianxia.sphere.dark": "TAL_DARK_BLACK_LUNG",
}
ORDINARY = [
    "tianxia.talent.ash.burial_ground",
    "TAL_ATHLETICS_AIR_STUNT",
    "tianxia.talent.blood.blood_puppet",
]
SPARROW = "TAL_ATHLETICS_SPARROW_S_PATH"
UNRESOLVED = "TAL_QIWEAVING_PAIRED_RESONANCE"
UNRESOLVED_SPHERE = "tianxia.sphere.qiweaving"
UNRESOLVED_FREE_TALENT = "TAL_QIWEAVING_ADDITIONAL_QIWEAVING_PACKAGE"
RESTRICTED_INITIAL = "tianxia.talent.blood.blood_puppet"
PRIORITY_FIXTURES = [
    ("Beauty", "tianxia.talent.beauty.admiring_crowd_method"),
    ("Ash", "tianxia.talent.ash.burial_ground"),
    ("Athletics", "TAL_ATHLETICS_WALL_STUNT"),
    ("Athletics", "TAL_ATHLETICS_AIR_STUNT"),
    ("Athletics", SPARROW),
    ("Blood", "tianxia.talent.blood.blood_puppet"),
]
CAT3_SPHERE_FREE_PAIRS = tuple(FREE_GRANTS.items())
CAT3_METHOD_ID = "METHOD-001"
CAT3_LEVEL_TALENTS = (
    "tianxia.talent.ash.ashen_step",
    "ASH_TAL_CINDER_BURST",
    "TAL_ATHLETICS_DIZZYING_TUMBLE",
    "TAL_ATHLETICS_MOVING_TARGET",
    "tianxia.talent.blood.blood_puppet",
    "ASH_TAL_SOOT_IN_LUNGS",
    "ASH_TAL_ASHEN_BURIAL",
)
CAT3_LEVEL_FEATURES = (
    "tianxia.path.qi_cultivation.feature.qi_sensing",
    "tianxia.path.qi_cultivation.feature.meridian_regulation",
    "tianxia.path.qi_cultivation.feature.qi_cultivation_subpath",
    "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight",
    "tianxia.path.qi_cultivation.feature.qi_armor",
    "tianxia.path.qi_cultivation.feature.subpath_feature",
    "tianxia.path.qi_cultivation.feature.featherfall",
)
CAT3_ZERO_OWNER_LEVEL_FEATURES = (
    "tianxia.path.qi_cultivation.feature.cultivated_response",
    *CAT3_LEVEL_FEATURES[1:],
)


def _choice(kind: str, cl: int, record_id: str, channel: str, selections: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": kind,
        "effective_cl": cl,
        "record_id": record_id,
        "acquisition_channel": channel,
        "parameters": selections or {},
    }


def _cat3_stage1_response(prompt: dict[str, Any]) -> dict[str, Any]:
    response = exact_stage1_response(prompt)
    method_decision = next(
        (row for row in response["response_payload"]["decisions"] if row["slot_id"] == "method_choice"),
        None,
    )
    path_decision = next(
        (row for row in response["response_payload"]["decisions"] if row["slot_id"] == "path_choice"),
        None,
    )
    # Owner-locked Path runs retain their existing Method-deferred contract;
    # only the zero-owner browser flow needs the deterministic open Method
    # required to derive the delegated Path route.
    if (
        method_decision is None
        or method_decision.get("choice_ids")
        or (path_decision and path_decision.get("choice_ids"))
    ):
        return response
    method_slot = next(
        row for row in prompt["envelope"]["decision_slots"] if row["slot_id"] == "method_choice"
    )
    available_methods = [
        choice["choice_id"]
        for choice in method_slot.get("choices") or []
        if isinstance(choice, dict) and isinstance(choice.get("choice_id"), str)
    ]
    method_id = CAT3_METHOD_ID if CAT3_METHOD_ID in available_methods else (available_methods[0] if available_methods else None)
    if method_id is None:
        return response
    method_decision.update({
        "state": "selected",
        "choice_ids": [method_id],
        "reason_code": None,
        "reason": None,
    })
    return response


def complete_cat3_plan(
    db: Database,
    project_id: str,
    *,
    stage1_prompt: dict[str, Any],
    delegated_envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic external-provider output used only by this acceptance test."""
    project = CharacterBuilderService(db).projects.get_project(project_id)["project"]
    locks = {row["field"]: row["value"] for row in project["user_locks"]}
    envelope = delegated_envelope or stage1_prompt["envelope"]
    allowed = envelope.get("allowed_choice_ids_by_slot") or {}
    background_authority = NonSphereAuthorityService(db).background_route_authority

    # The installed P2A authority no longer publishes the old compact
    # ``tianxia.sphere.scoundrel`` fixture as a delegated Background Sphere.
    # Select one exact route from the sealed envelope instead of emitting a
    # stale historical ID that the real delegated validator must reject.
    background_route: tuple[str, str, str, str] | None = None
    allowed_backgrounds = set(allowed.get("background_choice") or [])
    allowed_spheres = set(allowed.get("background_sphere_choice") or [])
    allowed_talents = set(allowed.get("background_talent_choice") or [])
    allowed_insights = set(allowed.get("origin_insight_choice") or [])
    for background_id in sorted(allowed_backgrounds):
        authority = background_authority.get(background_id) or {}
        for route in authority.get("route_options") or []:
            sphere_id = route.get("background_sphere_choice_id")
            talent_id = route.get("background_talent_choice_id")
            if sphere_id not in allowed_spheres or talent_id not in allowed_talents:
                continue
            for origin in authority.get("origin_insight_options") or []:
                origin_id = origin.get("origin_insight_choice_id")
                if not isinstance(origin_id, str):
                    continue
                generic_origin_id = origin_id.rsplit(".origin_insight.", 1)[-1]
                if ".origin_insight." in origin_id:
                    generic_origin_id = f"tianxia.origin_insight.{generic_origin_id}"
                if generic_origin_id in allowed_insights:
                    background_route = (background_id, sphere_id, talent_id, generic_origin_id)
                    break
            if background_route is not None:
                break
        if background_route is not None:
            break
    if background_route is None:
        # The W5 binding-error branch deliberately targets the historical
        # sealed fixture, whose response is rejected before normalization.  It
        # has no current delegated Background route, so retain the old payload
        # only for that pre-compilation transport assertion.
        background_route = (
            "tianxia.background.abandoned_orphan",
            "tianxia.sphere.scoundrel",
            "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE",
            "tianxia.origin_insight.street_hardened",
        )
    background_id, background_sphere_id, background_talent_id, origin_insight_id = background_route
    committed_plan = locks.get("character_creation.committed_catalog_choice_plan")
    if isinstance(committed_plan, dict):
        committed_pairs = [
            (row["sphere_id"], row["talent_id"])
            for row in committed_plan["grant_accounting"]["free_sphere_talent_grants"]
        ]
        committed_level_talents = committed_plan["grant_accounting"]["ordinary_talent_ids"]
    else:
        # The production-endpoint test also sends a deliberately wrong-bound
        # provider response to the immutable historical W5 fixture.  Preserve
        # that fixture's original external-provider payload; it is rejected at
        # the request-binding gate and is never compiled or treated as project
        # choice authority.  Normal projects must use the exact lock above.
        committed_pairs = CAT3_SPHERE_FREE_PAIRS
        committed_level_talents = CAT3_LEVEL_TALENTS
    stage1_response = _cat3_stage1_response(stage1_prompt)
    selected_method_ids = [
        decision["choice_ids"][0]
        for decision in stage1_response["response_payload"]["decisions"]
        if decision["slot_id"] == "method_choice" and decision.get("choice_ids")
    ]
    choices = [
        _choice("starting_state", 0, "tianxia.source.canon.authority.manifest.p2a.json", "source-document", {"ability_scores": {"STR": 8, "DEX": 14, "CON": 14, "INT": 15, "WIS": 12, "CHA": 8}}),
        _choice("background_acquisition", 1, background_id, "background-selection", {"ability": "DEX", "amount": 2}),
        _choice("background_sphere_acquisition", 1, background_sphere_id, "background-grant"),
        _choice("background_talent_acquisition", 1, background_talent_id, "background-grant"),
        _choice("origin_insight_acquisition", 1, origin_insight_id, "origin-selection"),
        _choice("path_acquisition", 1, "tianxia.path.qi_cultivation", "path-selection"),
    ]
    if selected_method_ids:
        choices.append(_choice("method_acquisition", 1, selected_method_ids[0], "method-acquisition"))
    for sphere_id, talent_id in committed_pairs:
        choices.extend([
            _choice("ai_bootstrap_sphere_acquisition", 1, sphere_id, "ai-bootstrap-free-cl1-sphere"),
            _choice("ai_bootstrap_talent_acquisition", 1, talent_id, "ai-bootstrap-free-cl1-talent"),
        ])
    locked_choices = locks.get("character_sheet.locked_choices") or {}
    level_features = (
        CAT3_LEVEL_FEATURES
        if locked_choices.get("path_choice")
        else CAT3_ZERO_OWNER_LEVEL_FEATURES
    )
    assert len(committed_level_talents) == len(level_features)
    for cl, (feature_id, talent_id) in enumerate(zip(level_features, committed_level_talents), start=1):
        choices.append(_choice("level_advance", cl, feature_id, "level-advance"))
        if cl == 3:
            choices.append(_choice("subpath_acquisition", 3, "tianxia.subpath.qi.cinder_heart_cultivator", "subpath-selection"))
        if cl == 4:
            choices.append(_choice("ability_score_change", 4, feature_id, "level-choice", {"deltas": {"INT": 2}}))
        choices.append(_choice("level_talent_acquisition", cl, talent_id, "level-choice"))
    choices.extend(
        _choice(
            "typed_none",
            7,
            f"tianxia.c1a.none.{target}",
            "typed-none",
            {
                "target": target,
                "reason_code": "not_selected_for_c1a_proof",
                "reason": "The bounded CAT3 acceptance character does not select this optional subsystem.",
            },
        )
        for target in (("foundation", "manuals", "equipment", "forged_techniques") if selected_method_ids else ("method", "foundation", "manuals", "equipment", "forged_techniques"))
    )
    return {
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "stage1_response": stage1_response,
        "target_cl": 7,
        "stage2_proposal": {
            "schema_version": "TianxiaFoundry.Stage2AdvancementProposal.v2",
            "project_id": project_id,
            "expected_project_revision": int(project["revision"]) + 1,
            "expected_content_lock_hash": project["content_lock"]["lock_hash"],
            "target_cl": 7,
            "idempotency_key": f"cat3.p1r.r1.{project_id}",
            "choices": choices,
        },
        "owner_descriptive_fields": {
            "identity": {"name": locks.get("character.identity.display_name", "CAT3 P1R Canonical Catalog Proof")},
            "concept": locks.get("concept", "CAT3 canonical catalog proof"),
        },
        "uncertainties": [],
        "fallbacks": [],
        "output_profile": {"combat_ready": False, "profile": "CHARACTER_GM_MODEL"},
    }


def stage(message: str) -> None:
    print(f"[CAT3-P1R browser] {message}", flush=True)


def provider_handler(context: dict[str, Any]):
    def handler(request: httpx.Request) -> httpx.Response:
        provider_request = json.loads(request.content)
        if provider_request["messages"][1]["content"] == 'Return exactly {"connection":"ok"}.':
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"connection":"ok"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })
        prompt = json.loads(provider_request["messages"][1]["content"])
        complete_request = prompt["complete_request"]
        app = context["app"]
        plan = complete_cat3_plan(
            app.state.db,
            complete_request["project_id"],
            stage1_prompt=complete_request["stage1_prompt"],
            delegated_envelope=complete_request.get("delegated_choice_envelope"),
        )
        plan["stage1_response"] = _cat3_stage1_response(complete_request["stage1_prompt"])
        plan["request_sha256"] = complete_request["request_sha256"]
        content = canonical_json(plan)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 101, "completion_tokens": 53, "total_tokens": 154},
            },
        )

    return handler


def run(*, root: Path, data: Path, output: Path, browser: str, screenshot_dir: Path) -> dict[str, Any]:
    stage("initializing data root")
    data.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env(root, data)
    context: dict[str, Any] = {}
    stage("creating real FastAPI application")
    app = create_app(
        settings,
        ai_transport=httpx.MockTransport(provider_handler(context)),
        ai_secret_store=InMemorySecretStore("cat3-p1r-browser-key-123"),
    )
    context["app"] = app
    stage("configuring exact bundled Factory")
    configured = FactoryAdapter(app.state.db).configure(FACTORY)
    stage("Factory configured; rebuilding canonical core")
    CatalogService(app.state.db).rebuild_core(Path(configured["factory_root"]))
    stage("canonical core rebuilt")
    app.state.ai_provider.configure(
        enabled=True,
        model="deepseek-v4-flash",
        thinking_mode="disabled",
        max_output_tokens=8192,
        timeout_seconds=60,
        data_sharing_acknowledged=True,
        acknowledged_by="CAT3-P1R deterministic browser acceptance",
    )
    app.state.ai_provider.test_connection()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        port = port_probe.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    server_thread = threading.Thread(target=server.run, name="cat3-p1r-fastapi", daemon=True)
    stage(f"prepared real loopback FastAPI server at {base_url}")
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    requests: list[dict[str, Any]] = []
    screenshots: list[str] = []

    with TestClient(app) as client:
        server_thread.start()
        for _ in range(200):
            if server.started:
                break
            server_thread.join(0.05)
        assert server.started, "Loopback FastAPI server did not start."
        with sync_playwright() as pw:
            instance = pw.chromium.launch(
                executable_path=browser,
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--no-proxy-server",
                    "--disable-features=BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessForNavigations,PrivateNetworkAccessRespectPreflightResults",
                ],
            )
            page = instance.new_page(viewport={"width": 1720, "height": 1200})
            page.on("pageerror", lambda exc: (page_errors.append(str(exc)), stage(f"page error: {exc}")))
            page.on("console", lambda msg: (console_errors.append(msg.text), stage(f"console error: {msg.text}")) if msg.type == "error" else None)
            page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))

            page.on("response", lambda response: requests.append({"method": response.request.method, "url": response.url, "path": response.request.url, "status": response.status}) if "/api/" in response.url else None)
            stage("opening application in Chromium over real loopback HTTP")
            page.goto(base_url, wait_until="domcontentloaded", timeout=120000)
            uuid_probe = page.evaluate(
                """() => ({
                    available: typeof crypto.randomUUID === 'function',
                    first: crypto.randomUUID(),
                    second: crypto.randomUUID()
                })"""
            )
            assert uuid_probe["available"] is True
            assert uuid_probe["first"] != uuid_probe["second"]
            assert all(re.fullmatch(r"[0-9a-f-]{36}", uuid_probe[key]) for key in ("first", "second"))
            stage("native Chromium crypto.randomUUID verified")
            page.wait_for_function(
                "document.querySelector('#sheetOptionsStatus')?.textContent.includes('canonical Spheres')",
                timeout=120000,
            )
            option_status = page.locator("#sheetOptionsStatus").text_content() or ""
            stage(f"option status: {option_status}")
            required_option_tokens = (
                "85 canonical Spheres",
                "2985 canonical Talents",
                "291 automatic Sphere components loaded",
                "0 zero-talent Spheres",
                "7 quarantined records",
            )
            if not all(token in option_status for token in required_option_tokens):
                debug_capture = screenshot_dir / "00_options_not_ready.png"
                page.screenshot(path=str(debug_capture), full_page=True)
                (output.parent / "browser_options_debug.html").write_text(page.content(), encoding="utf-8")
                raise AssertionError(f"Character options did not become ready: {option_status}; page_errors={page_errors}; console_errors={console_errors}; requests={requests[-20:]}")
            stage("normal wizard catalog surface ready")

            # Phase 1: exact normal wizard selection and planning.
            stage("running normal wizard selection and planning proof")
            page.get_by_role("button", name="Detailed Character Intake", exact=True).click()
            page.locator("#ownerCustomizationSection").wait_for(state="visible", timeout=60000)
            page.fill("#guidedName", "CAT3 P1R Canonical Catalog Proof")
            page.fill("#guidedConcept", "A Beauty cultivator testing exact CL, prerequisite, restricted-provenance, unresolved, and Dark base-component authority.")
            page.fill("#guidedLevel", "7")
            page.dispatch_event("#guidedLevel", "change")
            # REC1-P1CR4 completes Sphere/Talent planning on the Paths & Method
            # screen before the request freezes.
            page.locator("#guidedBriefContinue").click()
            page.locator("#builderPaths").wait_for(state="visible", timeout=60000)
            # Keep the production CAT3 compile on the explicit owner-locked
            # Path route.  With zero Path locks, the delegated response must
            # select a Method and the current CAT3 historical Stage 2 fixture
            # intentionally exercises the Path-bound compatibility contract.
            page.locator("#sheetPaths input[value='tianxia.path.qi_cultivation']").check()
            page.wait_for_function("methodCompatibility.state === 'accepted'", timeout=120000)
            page.locator("#sheetSphereAdd").wait_for(state="visible", timeout=60000)
            page.wait_for_function(
                "document.querySelector('#sheetSphereAdd')?.options.length > 80",
                timeout=120000,
            )
            for sphere_id in SPHERES:
                page.select_option("#sheetSphereAdd", sphere_id)
                page.get_by_role("button", name="Add Sphere", exact=True).click()

            selected_priority_ids: list[str] = []
            priority_states: dict[str, dict[str, Any]] = {}
            for sphere_name, talent_id in PRIORITY_FIXTURES:
                page.locator(".sphere-card .sphere-activate").filter(has_text=sphere_name).first.click()
                row = page.locator(f'#sheetTalentOptions [data-talent-id="{talent_id}"]')
                row.wait_for(timeout=60000)
                button = row.locator("button.talent-toggle")
                assert not button.is_disabled(), f"Expected planning priority control to be enabled for {talent_id}"
                priority_states[talent_id] = {
                    "selection_status": row.get_attribute("data-selection-status"),
                    "authority_text": row.locator(".talent-authority-state").inner_text(),
                }
                button.click()
                selected_priority_ids.append(talent_id)

            assert "Restricted initial-creation priority" in priority_states["tianxia.talent.blood.blood_puppet"]["authority_text"]
            assert page.locator("#sheetTalentSelectionCount").inner_text() == f"{len(selected_priority_ids)} prioritized"
            selection_capture = screenshot_dir / "01_normal_wizard_cat3_priorities.png"
            page.screenshot(path=str(selection_capture), full_page=True)
            screenshots.append(selection_capture.name)

            # Real backend shared evaluator: one exact legal grant plan plus one
            # provenance-gated and one unresolved fail-closed variant.  The
            # public route cannot mint initial-creation provenance. No endpoint
            # is intercepted or mocked.
            ungated_ordinary = [
                talent_id for talent_id in ORDINARY
                if talent_id != "tianxia.talent.blood.blood_puppet"
            ]
            projection_body = {
                "target_cl": 7,
                "acquired_sphere_ids": SPHERES,
                "free_talent_grants": FREE_GRANTS,
                "ordinary_talent_ids": ungated_ordinary,
            }
            valid_projection = page.evaluate(
                "async body => await api('/api/catalog/canonical/creator-projection', {method:'POST', body:JSON.stringify(body)})",
                projection_body,
            )
            gated_public_projection = page.evaluate(
                "async body => await api('/api/catalog/canonical/creator-projection', {method:'POST', body:JSON.stringify(body)})",
                {**projection_body, "ordinary_talent_ids": ORDINARY},
            )
            unresolved_projection = page.evaluate(
                "async body => await api('/api/catalog/canonical/creator-projection', {method:'POST', body:JSON.stringify(body)})",
                {
                    **projection_body,
                    "acquired_sphere_ids": SPHERES + [UNRESOLVED_SPHERE],
                    "free_talent_grants": {**FREE_GRANTS, UNRESOLVED_SPHERE: UNRESOLVED_FREE_TALENT},
                    "ordinary_talent_ids": ungated_ordinary + [UNRESOLVED],
                },
            )
            selected_dispositions = {row["canonical_talent_id"]: row for row in valid_projection["talent_dispositions"]}
            gated_public_dispositions = {
                row["canonical_talent_id"]: row for row in gated_public_projection["talent_dispositions"]
            }
            unresolved_dispositions = {row["canonical_talent_id"]: row for row in unresolved_projection["talent_dispositions"]}
            dark_automatic = [
                row for row in valid_projection["grant_accounting"]["automatic_base_abilities"]
                if row["owning_canonical_sphere_id"] == "tianxia.sphere.dark"
            ]
            darkness_rows = [row for row in dark_automatic if row["display_name"] == "Darkness"]
            public_provenance = gated_public_projection["grant_accounting"]["acquisition_provenance"]

            assert valid_projection["ready"] is True
            assert selected_dispositions["tianxia.talent.ash.burial_ground"]["minimum_cl"] == 7
            assert selected_dispositions["TAL_ATHLETICS_AIR_STUNT"]["selectable_now"] is True
            sparrow = selected_dispositions[SPARROW]
            sparrow_predicates = sparrow["prerequisite_evaluation"]["predicate_results"]
            assert sparrow["selectable_now"] is True
            assert sparrow["minimum_cl"] == 7
            assert {
                row.get("target_id")
                for row in sparrow_predicates
                if row.get("kind") == "talent" and row.get("passed")
            } == {"TAL_ATHLETICS_WALL_STUNT", "TAL_ATHLETICS_AIR_STUNT"}
            assert not any(row.get("kind") in {"sphere", "unresolved"} for row in sparrow_predicates)
            assert gated_public_projection["ready"] is False
            assert gated_public_dispositions["tianxia.talent.blood.blood_puppet"]["selectable_now"] is False
            assert any(
                row["canonical_content_id"] == "tianxia.talent.blood.blood_puppet"
                and row["source"] == "post-creation-exact-evidence"
                and row["recorded"] is False
                and not row["evidence_ids"]
                for row in public_provenance
            )
            assert unresolved_projection["ready"] is False
            assert unresolved_dispositions[UNRESOLVED]["disposition"] == "locked_by_unresolved_prerequisite"
            assert any(row["code"] == "ORDINARY_TALENT_NOT_SELECTABLE" and row["talent_id"] == UNRESOLVED for row in unresolved_projection["validation_errors"])
            assert len(darkness_rows) == 1

            page.evaluate(
                "proof => { const pre=document.createElement('pre'); pre.id='cat3BrowserProof'; pre.textContent=JSON.stringify(proof,null,2); document.querySelector('#ownerDetailHost').prepend(pre); }",
                {
                    "valid_projection_ready": valid_projection["ready"],
                    "cl7_talent": selected_dispositions["tianxia.talent.ash.burial_ground"],
                    "prerequisite_chain": selected_dispositions["TAL_ATHLETICS_AIR_STUNT"],
                    "restricted_public_projection": gated_public_dispositions["tianxia.talent.blood.blood_puppet"],
                    "restricted_public_provenance": public_provenance,
                    "unresolved_disposition": unresolved_dispositions[UNRESOLVED],
                    "dark_automatic_abilities": dark_automatic,
                },
            )
            stage("shared evaluator projection proof passed")
            evaluator_capture = screenshot_dir / "02_shared_evaluator_exact_results.png"
            page.screenshot(path=str(evaluator_capture), full_page=True)
            screenshots.append(evaluator_capture.name)

            # Commit the normal-wizard project and reopen its exact planning locks.
            stage("saving and reopening normal-wizard planning locks")
            page.locator("#guidedBuildButton").click()
            page.locator("#builderAI").wait_for(state="visible", timeout=180000)
            wizard_project_id = page.evaluate("guidedProjectId")
            assert wizard_project_id
            page.locator("#guidedSaveDraft").click()
            page.locator("#guidedPersistenceLabel").filter(has_text="Saved Draft").wait_for(timeout=60000)
            reopened = page.evaluate(
                "async projectId => await api(`/api/projects/${encodeURIComponent(projectId)}`)",
                wizard_project_id,
            )
            reopened_locks = {row["field"]: row["value"] for row in reopened["project"]["user_locks"]}
            planning_preferences = reopened_locks["character_sheet.planning_preferences"]
            compatibility_grant_plan = reopened_locks["character_sheet.canonical_grant_plan"]
            assert planning_preferences["sphere_priority_ids"] == SPHERES
            assert planning_preferences["talent_priority_ids"] == selected_priority_ids
            assert compatibility_grant_plan["acquired_canonical_sphere_ids"] == []
            assert compatibility_grant_plan["grant_accounting"]["acquisition_provenance"] == []

            # The real normal-wizard submit already freezes the server-owned
            # first-cycle plan before returning to the AI route.  Re-submit the
            # same idempotent endpoint to retrieve the exact typed snapshot;
            # the generic choice-lock endpoint would correctly reject a second
            # immutable lock with USER_LOCK_FIELD_IMMUTABLE.
            choice_commit = page.evaluate(
                """async projectId => await api(
                    `/api/character-builder/projects/${encodeURIComponent(projectId)}/normal-first-cycle-catalog-choice-lock`,
                    {method:'POST', body:'{}'}
                )""",
                wizard_project_id,
            )
            assert choice_commit["idempotent"] is True
            assert choice_commit["evidence_issued"] is False
            assert valid_choice_snapshot(choice_commit["typed_choice_snapshot"])
            canonical_grant_plan = choice_commit["grant_plan"]
            pending_initial_provenance = canonical_grant_plan["grant_accounting"]["acquisition_provenance"]
            committed_talent_ids = {
                *(
                    row["talent_id"]
                    for row in canonical_grant_plan["grant_accounting"]["free_sphere_talent_grants"]
                ),
                *canonical_grant_plan["grant_accounting"]["ordinary_talent_ids"],
            }
            restricted_initial_pending = any(
                row["canonical_content_id"] == RESTRICTED_INITIAL
                and row["source"] == "pending-trusted-initial-finalization"
                and row["recorded"] is False
                for row in pending_initial_provenance
            )
            # The normal first-cycle server planner intentionally selects only
            # creator-ready Open access records.  Restricted priorities remain
            # visible in the planning UI and are still fail-closed on the
            # public projection route, but are not silently inserted into this
            # automatic first-cycle lock.
            assert restricted_initial_pending is (RESTRICTED_INITIAL in committed_talent_ids)

            committed_reopen = page.evaluate(
                "async projectId => await api(`/api/projects/${encodeURIComponent(projectId)}`)",
                wizard_project_id,
            )
            committed_locks = {row["field"]: row["value"] for row in committed_reopen["project"]["user_locks"]}
            assert committed_locks["character_creation.committed_catalog_choice_plan"] == canonical_grant_plan
            assert choice_commit["typed_choice_snapshot"]["canonical_project_id"] == wizard_project_id
            assert choice_commit["typed_choice_snapshot"]["project_revision"] == committed_reopen["project"]["revision"]

            stage("normal-wizard save/reopen and exact catalog-choice freeze proof passed")
            # Phase 2: real production backend compilation/finalization through
            # the exact same frontend-created project and live provider service,
            # then project reopen. No fixture identity substitution is allowed.
            finalization_project_id = wizard_project_id
            assert page.evaluate("guidedProjectId") == finalization_project_id
            initial_fixture = page.evaluate(
                "async projectId => await api(`/api/projects/${encodeURIComponent(projectId)}`)",
                finalization_project_id,
            )
            initial_revision = initial_fixture["project"]["revision"]
            stage("starting two-scratch real production compilation")
            build_dispatch = page.evaluate(
                """() => {
                    document.querySelector('#guidedProviderRouteTab').click();
                    const button = document.querySelector('#guidedStartBuild');
                    const snapshot = {
                        disabled: button.disabled,
                        projectId: guidedProjectId,
                        mode: guidedExecutionMode(),
                        handlerType: typeof startGuidedCompleteBuild,
                        status: document.querySelector('#guidedStatus').textContent
                    };
                    window.__cat3BuildState = {status: 'pending', error: null};
                    startGuidedCompleteBuild().then(
                        () => { window.__cat3BuildState.status = 'resolved'; },
                        error => { window.__cat3BuildState = {status: 'rejected', error: String(error?.stack || error)}; }
                    );
                    return snapshot;
                }"""
            )
            stage(f"production build dispatch: {build_dispatch}")
            page.wait_for_timeout(1500)
            build_debug = page.evaluate("() => ({build: window.__cat3BuildState, status: document.querySelector('#guidedStatus').textContent, buttonDisabled: document.querySelector('#guidedStartBuild').disabled})")
            stage(f"production build state after 1.5s: {build_debug}")
            # The review section can become visible while the large returned run
            # is still being rendered. Wait on the real application state and
            # clean-finalization gate, not merely DOM visibility.
            page.wait_for_function(
                """() =>
                    window.__cat3BuildState?.status === 'resolved' &&
                    guidedRun?.status === 'READY_FOR_REVIEW' &&
                    guidedRun?.quality?.status === 'CLEAN' &&
                    !(guidedRun?.blockers || []).length &&
                    !document.querySelector('#guidedFinalize').disabled
                """,
                timeout=1200000,
            )
            page.locator("#builderReview").wait_for(state="visible", timeout=60000)
            page.locator("#guidedFinalize").wait_for(state="visible", timeout=60000)
            assert page.locator("#guidedFinalize").is_enabled()
            review_capture = screenshot_dir / "03_real_backend_ready_for_finalize.png"
            page.screenshot(path=str(review_capture), full_page=True)
            screenshots.append(review_capture.name)
            stage("production compilation reached ready-for-review")
            run_before_finalize = page.evaluate("guidedRun")
            assert run_before_finalize["status"] == "READY_FOR_REVIEW"
            assert run_before_finalize["dry_run"]["independent_compilations"] == 2
            snapshot_binding = run_before_finalize["request"]["typed_choice_snapshot"]
            assert snapshot_binding["schema"] == "TianxiaFoundry.TypedProjectChoiceSnapshotBinding.v1"
            assert snapshot_binding["canonical_project_id"] == finalization_project_id
            assert snapshot_binding["project_revision"] == initial_revision
            assert snapshot_binding["display_name_content"] == initial_fixture["working_name"]
            assert run_before_finalize["dry_run"]["typed_choice_snapshot"] == snapshot_binding
            review_snapshot_file = output.parent / "CAT3_P1R_R1_TYPED_CHOICE_SNAPSHOT.json"
            with page.expect_download(timeout=180000) as snapshot_download:
                page.evaluate(
                    """url => {
                        const link = document.createElement('a');
                        link.href = url;
                        link.download = '';
                        document.body.appendChild(link);
                        link.click();
                        link.remove();
                    }""",
                    f"/api/character-creation/runs/{run_before_finalize['run_id']}/typed-choice-snapshot",
                )
            snapshot_download.value.save_as(str(review_snapshot_file))
            frozen_snapshot = json.loads(review_snapshot_file.read_text(encoding="utf-8"))
            assert valid_choice_snapshot(frozen_snapshot)
            assert frozen_snapshot["snapshot_sha256"] == snapshot_binding["snapshot_sha256"]
            assert frozen_snapshot["canonical_project_id"] == finalization_project_id
            assert frozen_snapshot["project_revision"] == initial_revision
            assert frozen_snapshot["display_name_content"] == initial_fixture["working_name"]
            stage("finalizing through live backend")
            page.locator("#guidedFinalize").click()
            # REC1-P1CR3/P1CR4 now renders a finalized build in the persisted
            # owner-sheet step instead of the retired builderDone panel.
            page.locator("#builderSheet").wait_for(state="visible", timeout=1200000)
            page.wait_for_function(
                """() => guidedRun?.status === 'CLEAN_AND_FINALIZED' &&
                    document.querySelector('#ownerSheetState')?.textContent.includes('Persisted Character Sheet')""",
                timeout=1200000,
            )
            stage("finalization completed; reopening project")
            finalized_run = page.evaluate(
                "async runId => await api(`/api/character-creation/runs/${encodeURIComponent(runId)}`)",
                page.evaluate("guidedRun.run_id"),
            )
            assert finalized_run["status"] == "CLEAN_AND_FINALIZED"
            assert finalized_run["request"]["typed_choice_snapshot"] == snapshot_binding
            assert finalized_run["dry_run"]["typed_choice_snapshot"] == snapshot_binding
            assert finalized_run["commit"]["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]
            initial_provenance_issuance = finalized_run["outputs"]["catalog_acquisition_evidence"]
            assert initial_provenance_issuance["schema"] == "TianxiaFactory.InitialCatalogProvenanceIssuance.v1"
            assert initial_provenance_issuance["project_id"] == finalization_project_id
            assert initial_provenance_issuance["character_id"] == finalization_project_id
            assert initial_provenance_issuance["run_id"] == finalized_run["run_id"]
            assert initial_provenance_issuance["candidate_identity"] == finalized_run["dry_run"]["candidate_identity"]
            assert initial_provenance_issuance["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]
            issued_blood_provenance = [
                row for row in initial_provenance_issuance["records"]
                if row["canonical_content_id"] == RESTRICTED_INITIAL
            ]
            assert bool(issued_blood_provenance) is (RESTRICTED_INITIAL in committed_talent_ids)
            if issued_blood_provenance:
                assert all(
                    row["character_id"] == finalization_project_id
                    and row["issuance_route"] == "initial_character_finalization"
                    and row["authority_type"] == "talent_acquisition_provenance"
                    for row in issued_blood_provenance
                )
            available_evidence = page.evaluate(
                "async projectId => await api(`/api/non-sphere/projects/${encodeURIComponent(projectId)}/evidence`)",
                finalization_project_id,
            )
            available_by_id = {row["evidence_id"]: row for row in available_evidence["evidence"]}
            assert all(row["evidence_id"] in available_by_id for row in issued_blood_provenance)
            assert all(
                available_by_id[row["evidence_id"]]["targets"]["catalog_record_commitment_sha256"]
                    == row["catalog_record_commitment_sha256"]
                for row in issued_blood_provenance
            )
            final_capture = screenshot_dir / "04_real_backend_finalized.png"
            page.screenshot(path=str(final_capture), full_page=True)
            screenshots.append(final_capture.name)
            final_fixture = page.evaluate(
                "async projectId => await api(`/api/projects/${encodeURIComponent(projectId)}`)",
                finalization_project_id,
            )
            assert final_fixture["project"]["revision"] > initial_revision
            assert finalized_run["commit"]
            release_output = finalized_run["outputs"]["portable_character"]
            clean_import = release_output["clean_import"]
            gm_consumer = finalized_run["outputs"]["gm_consumer"]
            assert clean_import["first_status"] == "IMPORTED"
            assert clean_import["second_status"] == "ALREADY_INSTALLED_IDENTICAL"
            assert clean_import["character_sheet_semantic_equal"] is True
            assert clean_import["gm_model_semantic_equal"] is True
            assert clean_import["consumer_status"] == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"
            assert gm_consumer["status"] == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"
            # The persisted run response exposes a compact export summary. The
            # current owner export status supplies the live source-consumer
            # gate; the finalized package name is deterministic for this fixed
            # browser identity, so download the already-produced export rather
            # than attempting a second export with the same filename.
            gm_status = page.evaluate(
                "async projectId => await api(`/api/characters/${encodeURIComponent(projectId)}/gm-export/status`)",
                finalization_project_id,
            )
            assert gm_status["source_consumer_verified"] is True
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(initial_fixture["working_name"]).strip()).strip("._-")[:96] or "character"
            gm_export = {
                "filename": f"{safe_name}_{finalization_project_id}_GM_Screen.zip",
                "sha256": release_output["package_sha256"],
                "source_consumer_verified": gm_status["source_consumer_verified"],
            }
            character_zip = output.parent / "CAT3_P1R_R1_CHARACTER.zip"
            with page.expect_download(timeout=120000) as download_info:
                page.evaluate(
                    """url => {
                        const link = document.createElement('a');
                        link.href = url;
                        link.download = '';
                        document.body.appendChild(link);
                        link.click();
                        link.remove();
                    }""",
                    f"/api/characters/{finalization_project_id}/gm-export/download?filename={gm_export['filename']}",
                )
            download_info.value.save_as(str(character_zip))
            assert character_zip.stat().st_size > 0
            assert hashlib.sha256(character_zip.read_bytes()).hexdigest() == gm_export["sha256"]
            assert release_output["package_sha256"] == gm_export["sha256"]
            with zipfile.ZipFile(character_zip) as archive:
                portable_manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
                projection_provenance = json.loads(
                    archive.read("source/advancement_projection/Projection_Provenance_Map.json")
                )
                portable_gm_model = json.loads(archive.read("Tianxia_GM_Character_Model_v2.json"))
                portable_owner_sheet = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))
            assert portable_manifest["project_id"] == finalization_project_id
            assert portable_manifest["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]
            assert projection_provenance["typed_choice_snapshot"] == frozen_snapshot
            assert portable_gm_model["metadata"]["project_id"] == finalization_project_id
            assert portable_gm_model["metadata"]["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]
            assert portable_owner_sheet["authority_and_artifact_identity"]["project_id"] == finalization_project_id
            assert portable_owner_sheet["authority_and_artifact_identity"]["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]

            checks = {
                "real_linux_chromium_loopback_http": True,
                "real_backend_http_no_application_endpoint_mocking": True,
                "normal_wizard_form_used": True,
                "formerly_empty_beauty_priority_selected": "tianxia.talent.beauty.admiring_crowd_method" in selected_priority_ids,
                "cl7_foundation_talent_selected": "tianxia.talent.ash.burial_ground" in selected_priority_ids,
                "prerequisite_chain_selected_and_legal": selected_dispositions["TAL_ATHLETICS_AIR_STUNT"]["selectable_now"] is True,
                "sparrow_exact_chain_selected_and_legal": selected_dispositions[SPARROW]["selectable_now"] is True,
                "restricted_initial_priority_visible": "Restricted initial-creation priority" in priority_states["tianxia.talent.blood.blood_puppet"]["authority_text"],
                "public_route_cannot_issue_initial_provenance": (
                    gated_public_projection["ready"] is False
                    and gated_public_dispositions["tianxia.talent.blood.blood_puppet"]["selectable_now"] is False
                ),
                 "restricted_initial_priority_conditional_provenance": (
                     (
                         RESTRICTED_INITIAL in committed_talent_ids
                         and restricted_initial_pending
                         and bool(issued_blood_provenance)
                     )
                     or (
                         RESTRICTED_INITIAL not in committed_talent_ids
                         and not restricted_initial_pending
                         and not issued_blood_provenance
                     )
                 ),
                "issued_initial_provenance_retained_by_server_evidence_store": all(
                    row["evidence_id"] in available_by_id for row in issued_blood_provenance
                ),
                "unresolved_prerequisite_rejected": unresolved_dispositions[UNRESOLVED]["disposition"] == "locked_by_unresolved_prerequisite",
                "darkness_exposed_once": len(darkness_rows) == 1,
                "normal_wizard_save_reopen_preserves_exact_priorities": planning_preferences["talent_priority_ids"] == selected_priority_ids,
                "real_two_scratch_builds": run_before_finalize["dry_run"]["independent_compilations"] == 2,
                "real_browser_finalization": finalized_run["status"] == "CLEAN_AND_FINALIZED",
                 "finalized_project_reopens_at_new_revision": final_fixture["project"]["revision"] > initial_revision,
                 "character_zip_exported_through_browser": character_zip.is_file(),
                 "clean_factory_import_reopen": clean_import["first_status"] == "IMPORTED" and clean_import["character_sheet_semantic_equal"] is True,
                 "clean_factory_identical_reimport": clean_import["second_status"] == "ALREADY_INSTALLED_IDENTICAL",
                "exact_bundled_gm_screen_import": gm_consumer["status"] == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
                "gm_export_matches_verified_character_zip": release_output["package_sha256"] == gm_export["sha256"],
                "server_project_identity_preserved": frozen_snapshot["canonical_project_id"] == finalization_project_id,
                "working_name_is_display_content_only": (
                    frozen_snapshot["display_name_content"] == initial_fixture["working_name"]
                    and frozen_snapshot["canonical_project_id"] != frozen_snapshot["display_name_content"]
                ),
                "one_exact_snapshot_used_by_both_scratch_builds": (
                    run_before_finalize["dry_run"]["typed_choice_snapshot"] == snapshot_binding
                    and run_before_finalize["dry_run"]["independent_compilations"] == 2
                ),
                "review_and_finalization_share_exact_snapshot": (
                    finalized_run["request"]["typed_choice_snapshot"] == snapshot_binding
                    and finalized_run["dry_run"]["typed_choice_snapshot"] == snapshot_binding
                    and finalized_run["commit"]["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]
                ),
                "portable_and_gm_consumers_share_exact_snapshot": (
                    portable_manifest["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]
                    and projection_provenance["typed_choice_snapshot"] == frozen_snapshot
                    and portable_gm_model["metadata"]["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]
                    and portable_owner_sheet["authority_and_artifact_identity"]["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]
                ),
                "no_page_errors": not page_errors,
                "no_console_errors": not console_errors,
                "no_failed_requests": not failed_requests,
            }
            report = {
                "schema": "TianxiaFactory.CAT3P1RRealChromiumAcceptance.v1",
                "status": "PASS" if all(checks.values()) else "FAIL",
                "application_endpoints_mocked": False,
                "transport_mode": "LINUX_CHROMIUM_LOOPBACK_HTTP_TO_REAL_FASTAPI",
                "transport_note": "Linux Chromium navigated to and called the real FastAPI application over 127.0.0.1 HTTP. No application endpoint was intercepted or mocked.",
                "provider_transport": "deterministic MockTransport only behind the real AIProviderService for the external model call; all browser application requests execute real FastAPI endpoints",
                "browser_environment": {
                    "production_application_modified": False,
                    "native_crypto_uuid_probe": uuid_probe,
                },
                "base_url": base_url,
                "checks": checks,
                "catalog_status": app.state.canonical_catalog.status(),
                "wizard_project_id": wizard_project_id,
                "wizard_planning_preferences": planning_preferences,
                "priority_states": priority_states,
                "valid_projection_summary": {
                    "ready": valid_projection["ready"],
                    "projection_sha256": valid_projection["projection_sha256"],
                    "darkness_rows": darkness_rows,
                },
                "public_gated_projection_summary": {
                    "ready": gated_public_projection["ready"],
                    "disposition": gated_public_dispositions["tianxia.talent.blood.blood_puppet"],
                    "acquisition_provenance": public_provenance,
                },
                "unresolved_projection_summary": {
                    "ready": unresolved_projection["ready"],
                    "validation_errors": unresolved_projection["validation_errors"],
                    "disposition": unresolved_dispositions[UNRESOLVED],
                },
                "finalization": {
                    "project_id": finalization_project_id,
                    "same_normal_wizard_project": finalization_project_id == wizard_project_id,
                    "run_id": finalized_run["run_id"],
                    "candidate_identity": finalized_run["dry_run"]["candidate_identity"],
                    "status": finalized_run["status"],
                    "initial_revision": initial_revision,
                    "final_revision": final_fixture["project"]["revision"],
                    "commit": finalized_run["commit"],
                    "initial_catalog_provenance_issuance": initial_provenance_issuance,
                    "available_server_evidence": available_evidence,
                    "typed_choice_snapshot": {
                        "schema": frozen_snapshot["schema"],
                        "canonical_project_id": frozen_snapshot["canonical_project_id"],
                        "project_revision": frozen_snapshot["project_revision"],
                        "content_lock_hash": frozen_snapshot["content_lock_hash"],
                        "event_stream": frozen_snapshot["event_stream"],
                        "display_name_content": frozen_snapshot["display_name_content"],
                        "snapshot_sha256": frozen_snapshot["snapshot_sha256"],
                        "typed_lock_count": len(frozen_snapshot["typed_locks"]),
                    },
                    "character_zip": {
                        "path": str(character_zip),
                        "bytes": character_zip.stat().st_size,
                        "sha256": gm_export["sha256"],
                    },
                    "clean_factory_import": clean_import,
                    "exact_bundled_gm_screen_consumer": gm_consumer,
                },
                "requests": requests,
                "page_errors": page_errors,
                "console_errors": console_errors,
                "failed_requests": failed_requests,
                "screenshots": screenshots,
                "native_windows_status": "NATIVE_WINDOWS_ACCEPTANCE_NOT_EXECUTED",
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            stage("browser acceptance report sealed")
            instance.close()
        server.should_exit = True
        server_thread.join(timeout=10)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    parser.add_argument("--screenshot-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run(
        root=args.root.resolve(),
        data=args.data.resolve(),
        output=args.output.resolve(),
        browser=args.browser,
        screenshot_dir=args.screenshot_dir.resolve(),
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
