"""Public synthetic creation/Grow choices, persistence and human/AI combat menus."""
import copy
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings, sha256_json
from canonical_catalog import CanonicalCatalogAuthorityService
from character_creation import feature_choices
from character_sheet.service import CharacterSheetService
from combat.ext import formations as F
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from combat.gate2_runtime_content import AN
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000019"
AID = "actor:factory." + PID
SPHERE = "tianxia.sphere.formations"
PATH = "tianxia.path.qi_cultivation"
TRAINING = "FORMATIONS_BASE_FORMATION_TRAINING"
EXTRA = "tianxia.talent.formations.additional_pattern"
BASIC = {"locking_gate", "sensing_eye", "veiled_road", "nourishing_cycle", "suppressing_vein", "killing_line"}


def services(root):
    combat = CombatService(ROOT, root)
    table = TabletopService(combat, root)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return combat, table


def install(root, doc):
    folder = root / "portable_characters" / PID
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    return services(root)


def blank(cl=20):
    doc = sheet([], cl=cl, name="Pattern Student")
    doc["identity"].update(path_ids=[PATH], key_ability="INT")
    doc["path_and_subpath"] = {"path_record_id": PATH, "path_record_ids": [PATH]}
    doc["spheres_and_talents"] = {"sphere_record_ids": [], "learned_talent_record_ids": [],
                                 "automatic_sphere_component_record_ids": []}
    return doc


def creation_snapshot(root, monkeypatch, cl):
    """Real sheet producer with a tiny synthetic projection/display contract.

    No private character, history, build cache or owner data is used.
    """
    service = CharacterSheetService(Database(Settings.from_env(ROOT, root / "db")))
    texts = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    ids = [SPHERE, PATH, TRAINING, F.BASE_SET]
    descriptions = {SPHERE: "Formations sphere.", PATH: "Qi Cultivation Path.",
                    TRAINING: texts[TRAINING], F.BASE_SET: texts[F.BASE_SET]}
    names = {SPHERE: "Formations", PATH: "Qi Cultivation",
             TRAINING: "Formation Training", F.BASE_SET: "Set Array"}
    contract = {"rules": [{
        "record_id": rid, "display_name": names[rid],
        "section": "spheres" if rid == SPHERE else "paths" if rid == PATH else "features",
        "one_line_description": descriptions[rid], "full_description": descriptions[rid],
        "capabilities": {"character_sheet": "SUPPORTED", "combat_execution": "NOT_APPLICABLE"},
        "source": {"path": "synthetic/projection.json", "anchor": rid, "source_hash": sha256_json(rid)},
    } for rid in ids]}
    monkeypatch.setattr(service, "_display_contract", lambda *_: (contract, sha256_json(contract)))
    monkeypatch.setattr(service, "_readiness_profile", lambda: ({}, sha256_json({})))
    base = blank(cl)
    stats = base["ability_scores_and_statistics"]
    core = {"ability_scores": {r["ability"]: r["score"] for r in stats["abilities"]},
            "ability_modifiers": {r["ability"]: r["modifier"] for r in stats["abilities"]},
            "hp_max": 60, "hp_current": 60, "ac_base": 14, "ac_active": 14,
            "speed_ft": 30, "primary_resource_name": "Qi", "primary_resource_max": 30,
            "primary_resource_current": 30, "technique_attack_bonus": 8, "save_dc": 16}
    ledger = {"readiness": {"advancement": "ADVANCEMENT_READY"},
              "character": {"name": "Pattern Student", "cl": cl, "pb": 2, "path_id": PATH, "key_ability": "INT"},
              "core_stats": core, "path_selections": [{"path_id": PATH}],
              "automatic_sphere_components": [{"component_id": TRAINING}, {"component_id": F.BASE_SET}],
              "typed_none": {key: {"state": "none", "source_backed": True}
                             for key in ("method", "foundation", "manuals", "equipment", "forged_techniques", "immortal_arts")}}
    artifacts = {"Character_Master_Ledger.json": ledger,
                 "Rules_Selection_Packets.json": {"packets": [{"record_id": rid} for rid in ids]},
                 "Projection_Provenance_Map.json": {}, "Projection_Coverage_Report.json": {"valid": True},
                 "Projection_Diagnostics.json": {"valid": True}}
    document, artifact = service._build_snapshot(
        project={"project_id": PID, "revision": 1, "user_locks": []},
        artifacts=artifacts, projection_status={"projection_id": "synthetic-formation"})
    assert json.loads(Path(artifact["path"]).read_text()) == document
    return document


def assert_fight_patterns(root, expected, *, recorded=True):
    combat, table = services(root)
    mid = combat.create_factory_match(
        project_ids=[PID], opponent_actor_ids=[AN],
        control_modes={AID: "MANUAL", AN: "MANUAL"}, match_seed="FORMATION-LEARNING")["match_id"]
    # Compile and journal reload through the actual table service, not a plug-in call.
    engine = services(root)[0]._load_session(mid).engine
    actions = [a for a in engine.action_catalog.values() if a.owner_id == AID]
    for tag in ("set", "pulse"):
        rows = [a for a in actions if a.parameters.get(F.TAG) == tag]
        assert rows and {a.parameters["pattern"] for a in rows} == expected
    # The real engine's candidate menu feeds both seats.
    engine.state.current_slot_index = engine.state.initiative_order.index(AID)
    engine.state.current_actor_id = AID
    engine._system_start_turn()
    offered = [c for c in engine.legal_candidates()
               if engine.action_catalog[c.source_definition_id].parameters.get(F.TAG) == "set"]
    assert offered
    policy, _ = combat.policies.for_actor(AID)
    ai = build_decision_context(engine, policy, for_ai=True)
    ai_ids = {c.candidate_id for c in ai.legal_candidates}
    if recorded:
        assert {c.candidate_id for c in offered} <= ai_ids
    else:
        assert not {c.candidate_id for c in offered} & ai_ids


@pytest.mark.parametrize("cl", [1, 20])
def test_creation_asks_one_pattern_and_owner_answer_reaches_both_seats(tmp_path, monkeypatch, cl):
    doc = creation_snapshot(tmp_path, monkeypatch, cl)
    pending, = doc["spheres_and_talents"]["pending_feature_choices"]
    assert pending["feature_id"] == TRAINING
    assert {r["id"] for r in pending["options"]} == BASIC
    assert doc["spheres_and_talents"]["formation_patterns"] == [], "never guess for the owner"
    combat, table = install(tmp_path, doc)
    before = copy.deepcopy(doc)
    table.add_advancement(PID, "feature", TRAINING, feature_choices={TRAINING: "locking_gate"})
    reopened = services(tmp_path)[0]._factory_owner_sheet(PID)
    assert reopened["spheres_and_talents"]["formation_patterns"] == ["locking_gate"]
    assert reopened["spheres_and_talents"]["pending_feature_choices"] == []
    assert reopened["spheres_and_talents"]["known_feature_choices"] == ["Locking Gate"]
    assert doc == before
    assert_fight_patterns(tmp_path, {"locking_gate"})


def test_grow_sphere_and_repeat_talent_require_distinct_persisted_answers(tmp_path):
    combat, table = install(tmp_path, blank())
    gain = next(r for r in table.advancement(PID)["spheres"] if r["id"] == SPHERE)
    assert gain["feature_choices"][0]["feature_id"] == TRAINING
    for answer in ({}, {TRAINING: "not-a-pattern"}):
        with pytest.raises(FoundryError):
            table.add_advancement(PID, "sphere", SPHERE, feature_choices=answer)
        assert not services(tmp_path)[0]._factory_owner_sheet(PID)["spheres_and_talents"]["sphere_record_ids"]
    table.add_advancement(PID, "sphere", SPHERE, feature_choices={TRAINING: "locking_gate"})
    for pattern in ("sensing_eye", "veiled_road"):
        combat, table = services(tmp_path)
        talent = next(r for r in table.advancement(PID)["talents"] if r["id"] == EXTRA)
        assert "locking_gate" not in {o["id"] for o in talent["feature_choices"][0]["options"]}
        before = copy.deepcopy(combat._factory_owner_sheet(PID))
        with pytest.raises(FoundryError):
            table.add_advancement(PID, "talent", EXTRA, feature_choices={EXTRA: "locking_gate"})
        assert services(tmp_path)[0]._factory_owner_sheet(PID) == before
        table.add_advancement(PID, "talent", EXTRA, feature_choices={EXTRA: pattern})
    reopened = services(tmp_path)[0]._factory_owner_sheet(PID)
    assert reopened["spheres_and_talents"]["formation_patterns"] == ["locking_gate", "sensing_eye", "veiled_road"]
    assert reopened["spheres_and_talents"]["learned_talent_record_ids"].count(EXTRA) == 2
    assert_fight_patterns(tmp_path, {"locking_gate", "sensing_eye", "veiled_road"})


def test_legacy_fallback_is_unchanged_until_same_pending_choice_is_saved(tmp_path):
    doc = blank()
    doc["spheres_and_talents"].update(sphere_record_ids=[SPHERE],
        automatic_sphere_component_record_ids=[TRAINING, F.BASE_SET])
    before = copy.deepcopy(doc)
    combat, table = install(tmp_path, doc)
    pending, = table.advancement(PID)["pending_feature_choices"]
    assert pending["feature_id"] == TRAINING
    assert "formation_patterns" not in combat._factory_owner_sheet(PID)["spheres_and_talents"]
    assert_fight_patterns(tmp_path, BASIC, recorded=False)
    with pytest.raises((FoundryError, TabletopError)):
        table.add_advancement(PID, "feature", EXTRA, feature_choices={EXTRA: "sensing_eye"})
    table.add_advancement(PID, "feature", TRAINING, feature_choices={TRAINING: "nourishing_cycle"})
    reopened = services(tmp_path)[0]._factory_owner_sheet(PID)
    assert reopened["spheres_and_talents"]["formation_patterns"] == ["nourishing_cycle"]
    with pytest.raises((FoundryError, TabletopError)):
        table.add_advancement(PID, "feature", TRAINING, feature_choices={TRAINING: "locking_gate"})
    assert doc == before
    assert_fight_patterns(tmp_path, {"nourishing_cycle"})


def test_additional_pattern_level_up_uses_existing_feature_choices_payload(tmp_path):
    doc = blank(cl=1)
    doc["spheres_and_talents"].update(sphere_record_ids=[SPHERE],
        automatic_sphere_component_record_ids=[TRAINING, F.BASE_SET], formation_patterns=["Locking Gate"])
    combat, table = install(tmp_path, doc)
    info = table.advancement(PID)["level_up"]
    talent = next(r for r in info["talents"] if r["id"] == EXTRA)
    assert "locking_gate" not in {o["id"] for o in talent["feature_choices"][0]["options"]}
    choice = {"cl": 2, "talent_ids": [EXTRA], "subpaths": {}, "feature_choices": {EXTRA: "sensing_eye"}}
    table.level_up(PID, choice)
    reopened = services(tmp_path)[0]._factory_owner_sheet(PID)
    assert reopened["spheres_and_talents"]["formation_patterns"] == ["Locking Gate", "sensing_eye"]
    assert EXTRA not in reopened["path_and_subpath"]["feature_build_choices"]
    assert any(r["id"] == EXTRA for r in table.advancement(PID)["level_up"]["talents"])


def test_creation_and_grow_ui_submit_the_source_bound_feature_menu(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the DOM-free UI regression")
    source = (ROOT / "static/tabletop/grow.js").read_text().replace("export function", "function").replace("export async function", "async function")
    app = (ROOT / "static/app.js").read_text()
    owner = app[app.index("function ownerLearningChoices("):app.index("function renderOwnerSheet(")]
    pending = feature_choices.acquisition_menu({"spheres_and_talents": {"sphere_record_ids": [SPHERE]}})
    menu = {"cl": 20, "realm": "Immortal", "paths": [], "spheres": [], "talents": [],
            "pending_feature_choices": pending, "known_feature_choices": [],
            "added": {"spheres": [], "talents": [], "forged": []}}
    script = """
const assert = require("node:assert/strict");
const ids={}, calls=[];
function h(tag, attrs, ...children) {
  const n={tag,...(attrs || {}),children,listeners:{},appendChild(c){this.children.push(c);},
    addEventListener(k,fn){this.listeners[k]=fn;},replaceChildren(...c){this.children=c;}};
  if (attrs?.id) ids[attrs.id]=n;
  return n;
}
const root=h("div",{id:"grow-root"});
const gmEl=(tag,cls,text)=>h(tag,{class:cls},...(text ? [text] : []));
const plainAPIError=()=> "Could not record";
const api=async (url,opts)=>{calls.push({url,body:JSON.parse(opts.body)});return {};};
const openOwnerCharacterSheet=async ()=>{};
const current=MENU, training=TRAINING;
const walk=n=>n && typeof n === "object" ? [n,...(n.children || []).flatMap(walk)] : [];
""".replace("MENU", json.dumps(menu)).replace("TRAINING", json.dumps(TRAINING)) + source + owner + """
(async () => {
  initGrow({h,$:id=>ids[id],projectId:()=>"student",reloadSheet:async()=>{},toast(){},
    fetchJson:async (url,opts)=>{
      if (url === "/api/session") return {token:"synthetic"};
      if (!opts) return current;
      calls.push({url,body:JSON.parse(opts.body)});return current;
    }});
  await loadGrow();
  assert(ids["grow-feature-choices"]);
  onChange({target:{dataset:{featureRecord:training,featureChoice:training},value:"locking_gate"}});
  onClick({target:{closest:s=>s === "[data-grow-feature-save]" ? {dataset:{growFeatureSave:training}} : null}});
  await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
  assert.deepEqual(calls[0].body,{kind:"feature",record_id:training,feature_choices:{[training]:"locking_gate"}});
  const panel=ownerLearningChoices({project_id:"student",owner_character_sheet:{
    spheres_and_talents:{pending_feature_choices:current.pending_feature_choices}}});
  const nodes=walk(panel), select=nodes.find(n=>n.tag === "select"), button=nodes.find(n=>n.tag === "button");
  assert.equal(select.children.length,7);
  assert.equal(button.disabled,true);
  select.value="sensing_eye";select.listeners.change();assert.equal(button.disabled,false);
  await button.listeners.click();
  assert.deepEqual(calls[1].body,{kind:"feature",record_id:training,feature_choices:{[training]:"sensing_eye"}});
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
