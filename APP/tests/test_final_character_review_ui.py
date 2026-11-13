from __future__ import annotations

import json
import subprocess
import textwrap
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static/index.html").read_text(encoding="utf-8")
JS = (ROOT / "static/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static/styles.css").read_text(encoding="utf-8")


def _node(code: str) -> dict:
    completed = subprocess.run(
        ["node", "--input-type=module", "-"],
        cwd=ROOT.parent,
        input=textwrap.dedent(code),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.loads(completed.stdout)


def test_final_character_review_markup_and_static_contract() -> None:
    class IdParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.ids: list[str] = []

        def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.ids.extend(value for key, value in attrs if key == "id" and value)

    parser = IdParser()
    parser.feed(HTML)
    expected_ids = {
        "finalCharacterReviewPanel",
        "finalCharacterReviewPreview",
        "finalCharacterReviewStatus",
        "finalCharacterReviewIssueChallenge",
        "finalCharacterReviewApprovalStage",
        "finalCharacterReviewApprovalConfirm",
        "finalCharacterReviewApprove",
        "finalCharacterReviewMaterializeStage",
        "finalCharacterReviewMaterializeConfirm",
        "finalCharacterReviewMaterialize",
        "finalCharacterReviewAdvanced",
        "finalCharacterReviewTechnical",
    }
    assert expected_ids <= set(parser.ids)
    assert len(parser.ids) == len(set(parser.ids))
    assert HTML.count('class="final-character-review-receipt"') == 0  # cards are rendered from the validated triplet
    assert 'aria-live="polite"' in HTML
    assert 'type="checkbox"' in HTML
    assert 'min-height: 44px' in CSS
    assert ".final-character-review-stages { display: grid; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));" in CSS
    assert ".final-character-review-receipts, .final-character-review-stages { grid-template-columns: 1fr; }" in CSS
    assert "overflow-wrap: anywhere" in CSS

    route_base = "/api/characters/${encodeURIComponent(projectId)}/factory-workspace/final-character/"
    for suffix in ("preview", "approval-challenge", "approve", "materialize"):
        assert route_base + suffix in JS
    assert "void loadFinalCharacterReviewPreview(projectId, finalReviewRequestSerial);" in JS
    assert "finalCharacterReviewState.requestSerial === requestSerial" in JS
    assert "selectedProject === projectId" in JS
    assert "preview.components.length !== FINAL_CHARACTER_REVIEW_COMPONENTS.length" in JS
    assert "ordered.every(Boolean) ? ordered : null" in JS
    assert "async function finalCharacterReviewValidatedBinding" in JS
    assert "async function finalCharacterReviewValidChallenge" in JS
    assert "function finalCharacterReviewValidApproval" in JS
    assert "function finalCharacterReviewValidMaterialization" in JS
    assert "Rules-checked in the sealed character" in JS
    assert 'body: JSON.stringify({ttl_seconds: 300})' in JS
    assert 'body: JSON.stringify({challenge_id: envelope.challenge_id, nonce: envelope.nonce})' in JS
    assert 'body: JSON.stringify({review_record_id: reviewRecordId})' in JS
    assert 'approveButton) approveButton.disabled = state.busy || !state.challenge || Boolean(state.approval) || !approvalConfirm?.checked' in JS
    assert 'materializeButton) materializeButton.disabled = state.busy || !state.approval || state.approval.status !== "APPROVED" || Boolean(state.materialization) || !materializeConfirm?.checked' in JS
    assert "Date.parse(expiresAt)" in JS
    assert "finalCharacterReviewClearDownstream(\"This review challenge has expired." in JS
    assert "window.confirm" not in JS.split("async function issueFinalCharacterReviewChallenge", 1)[1].split("function wireFinalCharacterReviewControls", 1)[0]

    safe_challenge = JS.split("function finalCharacterReviewSafeChallenge", 1)[1].split("function finalCharacterReviewTechnicalSnapshot", 1)[0]
    assert "nonce:" not in safe_challenge
    materialize = JS.split("async function materializeFinalCharacterReview", 1)[1].split("function wireFinalCharacterReviewControls", 1)[0]
    assert "openOwnerCharacterSheet" not in materialize


def test_final_character_review_runs_real_app_js_with_dom_stub() -> None:
    result = _node(
        r'''
        import fs from "node:fs";
        import path from "node:path";
        import vm from "node:vm";
        import {createHash, webcrypto} from "node:crypto";
        import {TextEncoder} from "node:util";
        import {documentStub, registry} from "./APP/tests/gm_sheet_dom_stub/domstub.js";

        const staticRoot = path.resolve("APP/static");
        const readStatic = name => fs.readFileSync(path.join(staticRoot, name), "utf8");
        // The shared permissive stub does not parse select options; satisfy the
        // unrelated existing manual-lineage initializer before loading app.js.
        documentStub.getElementById("guidedManualLineageTrainingTypes").options = [{selected: false}];
        const sandbox = {
          console,
          setTimeout,
          clearTimeout,
          // app.js starts a page-lifetime interval at load; unref it so it
          // cannot keep this one-shot Node process alive after the result.
          setInterval: (...args) => setInterval(...args).unref(),
          clearInterval,
          AbortController,
          fetch: async () => { throw new Error("network disabled in focused test"); },
          location: {assign() {}, reload() {}},
          navigator: {userAgent: "final-review-ui-test"},
          crypto: webcrypto,
          TextEncoder,
          document: documentStub,
          localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
        };
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        sandbox.addEventListener = () => {};
        sandbox.removeEventListener = () => {};
        vm.createContext(sandbox);
        for (const file of ["sphere_talent_logic.js", "sheet_view_model.js", "complete_request_save.js", "app.js"]) {
          vm.runInContext(readStatic(file), sandbox, {filename: file});
        }

        const projectId = "project.final-review.ui";
        const hash = value => value.repeat(64);
        const stableJson = value => {
          if (value === null || typeof value !== "object") return JSON.stringify(value);
          if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
          return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
        };
        const digestJson = value => createHash("sha256").update(stableJson(value)).digest("hex");
        const bindingWithoutHash = {
          schema_version: "TianxiaFoundry.FinalCharacterReviewedBinding.v2",
          project_id: projectId,
          candidate_sha256: hash("1"),
          projection_id: "projection.final-review.ui",
          source_workspace_sha256: hash("2"),
          composite_overlay: {overlay_id: "overlay.composite", artifact_sha256: hash("3"), overlay_tree_sha256: hash("4"), files_tree_sha256: hash("5")},
          constructed_immortal_arts: (() => {
            const arts = {
              schema_version: "TianxiaFoundry.ConstructedImmortalArtBinding.v1",
              arts: [{immortal_art_id: "tianxia.constructed.immortal_art.ui", name: "Featherfall", cl_created: 15, action_id: "action.ui.featherfall", art_sha256: hash("6"), action_sha256: hash("7")}],
            };
            return {...arts, binding_sha256: digestJson(arts)};
          })(),
        };
        const binding = {...bindingWithoutHash, binding_sha256: digestJson(bindingWithoutHash)};
        const receipt = component => ({
          component,
          receipt_id: `component.${component}.${hash("a")}`,
          receipt_sha256: hash("b"),
          project_id: projectId,
          overlay_id: component === "composite_controller" ? binding.composite_overlay.overlay_id : "overlay.command4",
          artifact_sha256: component === "composite_controller" ? binding.composite_overlay.artifact_sha256 : hash("c"),
          overlay_tree_sha256: component === "composite_controller" ? binding.composite_overlay.overlay_tree_sha256 : hash("d"),
          files_tree_sha256: component === "composite_controller" ? binding.composite_overlay.files_tree_sha256 : hash("e"),
          candidate_sha256: hash("1"),
          projection_id: "projection.final-review.ui",
          source_workspace_sha256: hash("2"),
          request_sha256: null,
          response_sha256: null,
        });
        const preview = {
          schema_version: "TianxiaFoundry.FinalCharacterReviewPreview.v1",
          project_id: projectId,
          status: "READY_FOR_OWNER_APPROVAL",
          available: true,
          provider_calls: 0,
          binding,
          components: [receipt("command4"), receipt("composite_controller")],
        };
        const calls = [];
        let mutationMode = "normal";
        const challengeId = "challenge.final-review.ui";
        const reviewRecordId = `final-review.${hash("e")}`;
        const challengeResponse = () => ({
          schema_version: "TianxiaFoundry.FinalCharacterReviewApprovalChallenge.v1",
          project_id: projectId,
          status: "ISSUED",
          provider_calls: 0,
              binding_sha256: binding.binding_sha256,
              context: {
                schema_version: "TianxiaFoundry.FinalCharacterReviewApprovalContext.v1",
                project_id: projectId,
            candidate_sha256: binding.candidate_sha256,
            projection_id: binding.projection_id,
            source_workspace_sha256: binding.source_workspace_sha256,
            binding_sha256: binding.binding_sha256,
            operation: "final_character_reviewed_overlay_pair.approve",
            subject_type: "final_character_reviewed_overlay_pair",
            subject_id: binding.binding_sha256,
          },
          challenge: {
            challenge_id: challengeId,
            challenge_hash: hash("a"),
            operation: "final_character_reviewed_overlay_pair.approve",
            subject_type: "final_character_reviewed_overlay_pair",
            subject_id: binding.binding_sha256,
            exact_bytes_hash: digestJson(binding),
            binding_hash: digestJson(binding),
            project_lock_hash: binding.source_workspace_sha256,
            issued_at: "2999-01-01T00:00:00Z",
            expires_at: "2999-01-01T00:05:00Z",
            nonce: "hidden-test-nonce",
          },
        });
        const approvalResponse = () => ({
          schema_version: "TianxiaFoundry.FinalCharacterReviewSummary.v1",
          project_id: projectId,
          status: "APPROVED",
          provider_calls: 0,
          challenge_id: challengeId,
          evidence_id: "evidence.final-review.ui",
          review_record_id: reviewRecordId,
          record_sha256: hash("f"),
          binding_sha256: binding.binding_sha256,
        });
        const materializationResponse = () => ({
          schema_version: "TianxiaFoundry.FinalCharacterMaterializationSummary.v1",
          project_id: projectId,
          status: "MATERIALIZED",
          provider_calls: 0,
          idempotent: false,
          review_record_id: reviewRecordId,
          materialization_id: "materialization.final-review.ui",
          binding_sha256: binding.binding_sha256,
          output_tree_sha256: hash("1"),
        });
        const apiForTest = async (url, options = {}) => {
          calls.push({url, method: options.method || "GET", body: options.body ? JSON.parse(options.body) : null});
          if (url.endsWith("/preview")) return preview;
          if (url.endsWith("/approval-challenge")) {
            const result = challengeResponse();
            if (mutationMode === "challenge-wrong-binding") result.challenge.binding_hash = hash("c");
            if (mutationMode === "challenge-missing-nonce") delete result.challenge.nonce;
            return result;
          }
          if (url.endsWith("/approve")) {
            const result = approvalResponse();
            if (mutationMode === "approval-wrong-challenge") result.challenge_id = "challenge.other.ui";
            if (mutationMode === "approval-missing-record") delete result.review_record_id;
            if (mutationMode === "approval-wrong-binding") result.binding_sha256 = hash("0");
            return result;
          }
          if (url.endsWith("/materialize")) {
            const result = materializationResponse();
            if (mutationMode === "materialize-wrong-record") result.review_record_id = `final-review.${hash("0")}`;
            if (mutationMode === "materialize-missing-binding") delete result.binding_sha256;
            if (mutationMode === "materialize-wrong-binding") result.binding_sha256 = hash("0");
            if (mutationMode === "materialize-impossible-already") result.status = "ALREADY_MATERIALIZED";
            if (mutationMode === "materialize-impossible-materialized") result.idempotent = true;
            return result;
          }
          throw new Error(`unexpected route ${url}`);
        };
        sandbox.api = apiForTest;
        const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
        const element = id => registry.get(id);
        vm.runInContext(`selectedProject = ${JSON.stringify(projectId)}; globalThis.__reviewSerial = resetFinalCharacterReviewState(${JSON.stringify(projectId)});`, sandbox);
        await sandbox.loadFinalCharacterReviewPreview(projectId, sandbox.__reviewSerial);
        const issue = element("finalCharacterReviewIssueChallenge");
        const approvalConfirm = element("finalCharacterReviewApprovalConfirm");
        const approve = element("finalCharacterReviewApprove");
        const materializeConfirm = element("finalCharacterReviewMaterializeConfirm");
        const materialize = element("finalCharacterReviewMaterialize");
        const cardsBefore = element("finalCharacterReviewPreview").querySelectorAll(".final-character-review-receipt").length;
        const advancedBeforeIssue = element("finalCharacterReviewAdvanced").hidden;
        const technicalBeforeIssue = element("finalCharacterReviewTechnical").textContent;
        const challengeCallsBeforeIssue = calls.filter(call => call.url.endsWith("/approval-challenge")).length;
        const approveCallsBeforeConfirm = calls.filter(call => call.url.endsWith("/approve")).length;
        await sandbox.issueFinalCharacterReviewChallenge();
        const technicalAfterChallenge = element("finalCharacterReviewTechnical").textContent;
        const approveDisabledBeforeConfirm = approve.disabled;
        await sandbox.approveFinalCharacterReview();
        const approveCallsWithoutConfirm = calls.filter(call => call.url.endsWith("/approve")).length;
        approvalConfirm.checked = true;
        approvalConfirm.onchange();
        const approveEnabledAfterConfirm = !approve.disabled;
        await sandbox.approveFinalCharacterReview();
        const materializeDisabledBeforeConfirm = materialize.disabled;
        materializeConfirm.checked = true;
        materializeConfirm.onchange();
        const materializeEnabledAfterConfirm = !materialize.disabled;
        await sandbox.materializeFinalCharacterReview();

        const malformedPreviews = [
          {...preview, components: [preview.components[0], preview.components[1], preview.components[0]]},
          {...preview, components: preview.components.map((row, index) => index === 1 ? {...row, project_id: "project.other.ui"} : row)},
          {...preview, components: preview.components.map((row, index) => index === 1 ? {...row, receipt_id: ""} : row)},
          {...preview, binding: {...preview.binding, constructed_immortal_arts: {...preview.binding.constructed_immortal_arts, arts: preview.binding.constructed_immortal_arts.arts.map(art => ({...art, cl_created: 14}))}}},
        ];
        const malformedIssueDisabled = [];
        for (const malformed of malformedPreviews) {
          sandbox.api = async url => {
            if (url.endsWith("/preview")) return malformed;
            throw new Error(`unexpected malformed-case route ${url}`);
          };
          vm.runInContext(`selectedProject = ${JSON.stringify(projectId)}; globalThis.__malformedSerial = resetFinalCharacterReviewState(${JSON.stringify(projectId)});`, sandbox);
          await sandbox.loadFinalCharacterReviewPreview(projectId, sandbox.__malformedSerial);
          malformedIssueDisabled.push(element("finalCharacterReviewIssueChallenge").disabled);
        }

        const resetReady = async () => {
          mutationMode = "normal";
          sandbox.api = apiForTest;
          vm.runInContext(`selectedProject = ${JSON.stringify(projectId)}; globalThis.__caseSerial = resetFinalCharacterReviewState(${JSON.stringify(projectId)});`, sandbox);
          await sandbox.loadFinalCharacterReviewPreview(projectId, sandbox.__caseSerial);
        };
        const challengeNegativeCases = [];
        for (const mode of ["challenge-wrong-binding", "challenge-missing-nonce"]) {
          await resetReady();
          mutationMode = mode;
          await sandbox.issueFinalCharacterReviewChallenge();
          challengeNegativeCases.push({mode, issueDisabled: element("finalCharacterReviewIssueChallenge").disabled, approvalHidden: element("finalCharacterReviewApprovalStage").hidden});
        }
        const approvalNegativeCases = [];
        for (const mode of ["approval-wrong-challenge", "approval-missing-record", "approval-wrong-binding"]) {
          await resetReady();
          await sandbox.issueFinalCharacterReviewChallenge();
          mutationMode = mode;
          const confirm = element("finalCharacterReviewApprovalConfirm");
          confirm.checked = true;
          confirm.onchange();
          await sandbox.approveFinalCharacterReview();
          approvalNegativeCases.push({mode, status: element("finalCharacterReviewStatus").textContent, approvalHidden: element("finalCharacterReviewApprovalStage").hidden, materializeHidden: element("finalCharacterReviewMaterializeStage").hidden});
        }
        const materializationNegativeCases = [];
        for (const mode of ["materialize-wrong-record", "materialize-missing-binding", "materialize-wrong-binding", "materialize-impossible-already", "materialize-impossible-materialized"]) {
          await resetReady();
          await sandbox.issueFinalCharacterReviewChallenge();
          const approvalConfirm = element("finalCharacterReviewApprovalConfirm");
          approvalConfirm.checked = true;
          approvalConfirm.onchange();
          await sandbox.approveFinalCharacterReview();
          mutationMode = mode;
          const confirm = element("finalCharacterReviewMaterializeConfirm");
          confirm.checked = true;
          confirm.onchange();
          await sandbox.materializeFinalCharacterReview();
          materializationNegativeCases.push({mode, status: element("finalCharacterReviewStatus").textContent, materializeHidden: element("finalCharacterReviewMaterializeStage").hidden});
        }

        const staleProject = "project.stale.ui";
        let resolveStale;
        sandbox.api = async () => new Promise(resolve => { resolveStale = resolve; });
        vm.runInContext(`selectedProject = ${JSON.stringify(staleProject)}; globalThis.__staleSerial = resetFinalCharacterReviewState(${JSON.stringify(staleProject)});`, sandbox);
        const staleLoad = sandbox.loadFinalCharacterReviewPreview(staleProject, sandbox.__staleSerial);
        vm.runInContext(`selectedProject = "project.newer.ui"; resetFinalCharacterReviewState("project.newer.ui");`, sandbox);
        resolveStale({...preview, project_id: staleProject});
        await staleLoad;
        await flush();

        console.log(JSON.stringify({
          cardsBefore,
          advancedBeforeIssue,
          technicalBeforeIssue,
          challengeCallsBeforeIssue,
          approveDisabledBeforeConfirm,
          approveCallsBeforeConfirm,
          approveCallsWithoutConfirm,
          approveEnabledAfterConfirm,
          materializeDisabledBeforeConfirm,
          materializeEnabledAfterConfirm,
          malformedIssueDisabled,
          challengeNegativeCases,
          approvalNegativeCases,
          materializationNegativeCases,
          methods: calls.map(call => ({suffix: call.url.split("/").at(-1), method: call.method, body: call.body})),
          nonceRendered: technicalAfterChallenge.includes("hidden-test-nonce") || /"nonce"\s*:/.test(technicalAfterChallenge),
          stalePanelHidden: element("finalCharacterReviewPanel").hidden,
          staleCards: element("finalCharacterReviewPreview").querySelectorAll(".final-character-review-receipt").length,
          materializedStatus: element("finalCharacterReviewStatus").textContent,
        }));
        ''',
    )
    assert result["cardsBefore"] == 3
    assert result["advancedBeforeIssue"] is False
    assert "binding_sha256" in result["technicalBeforeIssue"]
    for component in ("command4", "composite_controller", "constructed_immortal_arts"):
        assert component in result["technicalBeforeIssue"]
    assert result["challengeCallsBeforeIssue"] == 0
    assert result["approveDisabledBeforeConfirm"] is True
    assert result["approveCallsBeforeConfirm"] == 0
    assert result["approveCallsWithoutConfirm"] == 0
    assert result["approveEnabledAfterConfirm"] is True
    assert result["materializeDisabledBeforeConfirm"] is True
    assert result["materializeEnabledAfterConfirm"] is True
    assert result["malformedIssueDisabled"] == [True, True, True, True]
    assert all(case["issueDisabled"] and case["approvalHidden"] for case in result["challengeNegativeCases"])
    assert all(case["status"] == "Review unavailable" and case["approvalHidden"] and case["materializeHidden"] for case in result["approvalNegativeCases"])
    assert all(case["status"] == "Review unavailable" and case["materializeHidden"] for case in result["materializationNegativeCases"])
    assert result["nonceRendered"] is False
    assert result["stalePanelHidden"] is True
    assert result["staleCards"] == 0
    assert result["materializedStatus"] == "Preview unavailable"
    mutation_calls = [call for call in result["methods"] if call["method"] == "POST"]
    assert mutation_calls[0]["body"] == {"ttl_seconds": 300}
    assert mutation_calls[1]["body"] == {"challenge_id": "challenge.final-review.ui", "nonce": "hidden-test-nonce"}
    assert mutation_calls[2]["body"] == {"review_record_id": "final-review." + "e" * 64}
