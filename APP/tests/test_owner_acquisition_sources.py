"""The ordinary Factory review must expose every proposed acquisition lane."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess

from app.api import _owner_view


def _proposal_run(*, background_locked=False):
    slots = {
        "background_choice": ["background.test"],
        "background_sphere_choice": ["background.scoundrel"],
        "background_talent_choice": ["background.hidden"],
        "sphere_priorities": ["sphere.death"],
        "advancement_skeleton": ["talent.weave"],
    }
    names = {
        "background_choice": {"background.test": {"name": "Public Background"}},
        "background_sphere_choice": {"background.scoundrel": {"name": "Scoundrel"}},
        "background_talent_choice": {"background.hidden": {"name": "Hidden Tool Cache"}},
        "sphere_priorities": {"sphere.death": {"name": "Death"}, "sphere.scoundrel": {"name": "Scoundrel"}, "sphere.smoke": {"name": "Smoke"}},
        "advancement_skeleton": {"talent.weave": {"name": "Bob and Weave"}, "talent.ward": {"name": "Bone Ward"}, "talent.veil": {"name": "Veil"}, "talent.test": {"name": "Training Talent"}},
    }
    locks = {key: slots.pop(key) for key in list(slots) if key.startswith("background")} if background_locked else {}
    return {
        "run_id": "public-source-review", "project_id": "public-source-project", "status": "NEEDS_REVIEW",
        "request": {"request_sha256": "a" * 64, "delegated_choice_envelope": {
            "choices_by_slot": names, "owner_locks": {"by_slot": locks},
            "typed_choice_authority_by_slot": {"advancement_skeleton": {"stage2_authority_by_choice": {"talent.weave": {"sphere_id": "sphere.scoundrel"}}}},
            "creation_training_contract": {"records": {"talent.test": {"owning_sphere_id": "sphere.death"}}},
        }},
        "response": {"parsed_plan": {
            "selection_intent": {"by_slot": slots},
            "acquisition_intent": {
                "sphere_free_talent_pairs": [{"sphere_id": "sphere.death", "talent_id": "talent.ward"}],
                "ordinary_talent_ids": ["talent.weave"],
                "trained_choices": [
                    {"cl": 1, "slot": 1, "choice_type": "new_sphere", "record_id": "sphere.smoke", "bonus_talent_id": "talent.veil", "source": {"route": "published_legal_teaching_route"}, "outcome": {"slot_cost": 1}},
                    {"cl": 1, "slot": 2, "choice_type": "known_sphere_talent", "record_id": "talent.test", "source": {"route": "recorded_self_training"}, "outcome": {"slot_cost": 1}},
                ],
            },
        }},
    }


def test_review_preserves_training_and_free_sources_without_granting_them():
    run = _proposal_run()
    before = deepcopy(run)
    owner = _owner_view(run)
    proposal = owner["proposal"]
    assert run == before
    assert proposal["status"] == "parsed_proposal_not_compiled"
    assert not owner["scratch_candidate"]["available"]
    assert proposal["background_sphere"][0]["name"] == "Scoundrel"
    assert proposal["background_talent"][0]["name"] == "Hidden Tool Cache"
    acquisitions = proposal["acquisitions"]
    assert acquisitions["ordinary_talents"] == ["Bob and Weave"]
    assert acquisitions["level_talents"][0]["sphere"] == "Scoundrel"
    assert acquisitions["level_talents"][0]["cl"] == 1
    assert [row["name"] for row in acquisitions["trained_choices"]] == ["Smoke", "Training Talent"]
    assert [row["slot"] for row in acquisitions["trained_choices"]] == [1, 2]
    assert all(row["outcome"]["slot_cost"] == 1 for row in acquisitions["trained_choices"])
    assert acquisitions["trained_choices"][1]["sphere"] == "Death"
    assert [(row["name"], row["sphere"], row["cl"]) for row in acquisitions["new_sphere_bonus_talents"]] == [("Veil", "Smoke", 1)]
    assert all(row["state"] == "proposed" for row in acquisitions["trained_choices"])


def test_review_shows_owner_locked_background_omitted_from_ai_selections():
    proposal = _owner_view(_proposal_run(background_locked=True))["proposal"]
    for field, expected in [("background", "Public Background"), ("background_sphere", "Scoundrel"), ("background_talent", "Hidden Tool Cache")]:
        assert proposal[field][0]["name"] == expected
        assert proposal[field][0]["provenance"] == "Owner"
        assert proposal[field][0]["state"] == "proposed"


def test_rendered_review_separates_sources_and_opens_background_groups():
    proposal = _owner_view(_proposal_run(background_locked=True))["proposal"]
    script = r"""
const fs = require('node:fs'); const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(input.path, 'utf8');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; }
  appendChild(node) { this.children.push(node); return node; }
  append(...nodes) { this.children.push(...nodes); }
  get childElementCount() { return this.children.length; }
}
const nodes = {};
const document = {createElement: tag => new Element(tag), getElementById: id => nodes[id] ||= new Element('div')};
const context = {document, ownerViewFor: run => run.owner_view, planningIsEditable: () => false, clearNode: node => {node.children = [];}};
vm.createContext(context);
for (const name of ['ownerText', 'friendlyLabel', 'appendCompiledRecord', 'appendCompiledEmpty', 'proposalAcquisitionSummary', 'renderProposalSphereInventory', 'renderCompiledOwnerStages']) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`Missing rendered function ${name}`);
  let end = source.indexOf('\nfunction ', start + 1);
  if (end < 0) end = source.length;
  vm.runInContext(source.slice(start, end), context);
}
context.renderCompiledOwnerStages({owner_view: {proposal: input.proposal}});
const text = node => [node.textContent, ...node.children.map(text)].filter(Boolean).join(' ');
console.log(JSON.stringify({
  intro: nodes.ownerCompiledSpheresIntro.textContent,
  label: nodes.ownerCompiledSpheresLabel.textContent,
  heading: nodes.ownerCompiledSpheresHeading.textContent,
  summary: nodes.ownerCompiledSphereSummary.textContent,
  legacySummary: context.proposalAcquisitionSummary({acquisitions: {}}),
  groups: nodes.ownerCompiledSpheresBody.children.map(node => ({label: node.children[0].textContent, open: node.open, text: text(node)})),
}));
"""
    result = subprocess.run(["node", "-e", script], input=json.dumps({"path": str(Path(__file__).resolve().parents[1] / "static/app.js"), "proposal": proposal}), text=True, capture_output=True, check=True)
    view = json.loads(result.stdout)
    groups = {row["label"]: row for row in view["groups"]}
    inventory = next(row for label, row in groups.items() if label.startswith("Sphere inventory · "))
    assert inventory["open"] is True
    assert inventory["label"].startswith("Sphere inventory · 3 Spheres · 5 Talents")
    for expected in ("Scoundrel", "Death", "Smoke", "Veil", "Background", "Starting grant", "Training", "New-Sphere bonus"):
        assert expected in inventory["text"]
    assert not any(label.startswith("Missing mandatory") for label in groups)
    assert groups["Background Sphere · 1"]["open"] is True
    assert "Scoundrel" in groups["Background Sphere · 1"]["text"]
    assert "Hidden Tool Cache" in groups["Background Talent · 1"]["text"]
    assert "Bone Ward" in groups["Starting free Sphere/Talent grants · 1"]["text"]
    assert "Bob and Weave" in groups["Free level Talents · 1"]["text"]
    assert "Scoundrel" in groups["Free level Talents · 1"]["text"]
    assert "CL 1" in groups["Trained choices · 2"]["text"]
    assert "Slot 2" in groups["Trained choices · 2"]["text"]
    assert "1 training choice" in groups["Trained choices · 2"]["text"]
    assert "Veil" in groups["Free talents from new Spheres · 1"]["text"]
    assert "Free" in groups["Free talents from new Spheres · 1"]["text"]
    assert "2 trained choices" in view["summary"]
    assert "1 free level Talent" in view["summary"]
    assert "1 new-Sphere bonus Talent" in view["summary"]
    assert "Nothing is granted until compilation succeeds" in view["intro"]
    assert view["label"] == "Proposed acquisitions"
    assert view["heading"] == "Proposed Spheres and Talents"
    assert "Training details unavailable" in view["legacySummary"]
    assert "0 trained choices" not in view["legacySummary"]


def test_review_sphere_inventory_groups_holdings_requests_and_missing_steps():
    run = _proposal_run()
    envelope = run["request"]["delegated_choice_envelope"]
    envelope["choices_by_slot"]["advancement_skeleton"]["talent.hidden.canonical"] = {"name": "Hidden Tool Cache"}
    envelope["choices_by_slot"]["sphere_priorities"]["sphere.ash"] = {"name": "Ash"}
    envelope["typed_choice_authority_by_slot"]["background_choice"] = {
        "background_package_linkage": {
            "background.test": [{
                "background_sphere_choice_id": "background.scoundrel",
                "canonical_sphere_id": "sphere.scoundrel",
                "background_talent_choice_id": "background.hidden",
                "talent_record_id": "talent.hidden.canonical",
            }]
        }
    }
    run["request"]["stage1_prompt"] = {"envelope": {"user_locks": [
        {"field": "character_sheet.planning_preferences", "value": {"sphere_priority_ids": ["sphere.death", "sphere.ash"]}},
    ]}}
    run["blockers"] = [{
        "code": "DCC_LINEAR_REQUIRED_STEP_UNSATISFIABLE",
        "message": "A required constructed-training slot has no legal option in the frozen request.",
        "details": {
            "step_id": "creation_training:2:3", "cl": 2, "slot": 3, "target_cl": 2, "required_choices_per_cl": 3,
            "reason": "no_legal_constructed_training_candidate",
            "known_sphere_ids": ["sphere.death", "sphere.scoundrel", "sphere.smoke"],
            "new_sphere_route_count": 82, "new_sphere_routes_without_exact_training_authority": 82,
            "known_sphere_talent_route_count": 59, "known_sphere_talent_routes_unused": 0,
            "owner_sphere_priority_ids": ["sphere.death", "sphere.ash"],
        },
    }]
    inventory = _owner_view(run)["proposal"]["sphere_inventory"]
    by_name = {row["name"]: row for row in inventory["holdings"]}
    assert list(by_name) == ["Scoundrel", "Death", "Smoke"]
    assert by_name["Scoundrel"]["source"] == "Background"
    assert by_name["Death"]["source"] == "Starting grant" and by_name["Death"]["cl"] == 1 and by_name["Death"]["requested"] is True
    assert by_name["Smoke"]["source"] == "Training" and by_name["Smoke"]["cl"] == 1 and by_name["Smoke"]["slot"] == 1
    assert [(t["name"], t["source"]) for t in by_name["Scoundrel"]["talents"]] == [("Hidden Tool Cache", "Background Talent"), ("Bob and Weave", "Free level Talent")]
    assert [(t["name"], t["source"], t["cl"]) for t in by_name["Death"]["talents"]] == [("Bone Ward", "Starting free Talent", 1), ("Training Talent", "Trained", 1)]
    assert [(t["name"], t["source"]) for t in by_name["Smoke"]["talents"]] == [("Veil", "New-Sphere bonus")]
    assert all(row["state"] == "proposed" for row in inventory["holdings"])
    assert inventory["unassigned_talents"] == []
    assert [row["name"] for row in inventory["requested_not_acquired"]] == ["Ash"]
    assert [row["acquired"] for row in inventory["requested"]] == [True, False]
    assert len(inventory["missing_mandatory"]) == 1
    gap = inventory["missing_mandatory"][0]
    assert gap["step_id"] == "creation_training:2:3"
    assert "CL 2 slot 3" in gap["summary"]
    assert "82 of 82" in gap["detail"]
    assert inventory["counts"] == {"spheres": 3, "validated_spheres": 0, "talents": 5, "requested": 2, "requested_not_acquired": 1, "missing_mandatory": 1}
