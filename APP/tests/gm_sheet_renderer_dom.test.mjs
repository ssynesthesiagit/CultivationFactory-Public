// Focused headless renderer gate for the GM-style Character Sheet stage.
// Run: node --test APP/tests/gm_sheet_renderer_dom.test.mjs
//
// Executes the REAL APP/static/app.js top-level wiring plus
// renderCharacterLibrary and renderOwnerSheet against a permissive in-process
// DOM stub and the synthetic Scratch fixture. This protects the deferred
// rendered-acceptance criteria (final name visible, no placeholder leak, tabs,
// attention state, technical details closed by default) deterministically,
// without any browser.
import test, {after} from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const WT = path.resolve(here, "..", "..");
const {documentStub, registry} = await import("./gm_sheet_dom_stub/domstub.js");

function readStatic(name) {
  return fs.readFileSync(path.join(WT, "APP", "static", name), "utf8");
}
const fixture = JSON.parse(fs.readFileSync(path.join(here, "fixtures/gm_sheet/scratch_owner_sheet_snapshot.fixture.json"), "utf8"));
const libraryRows = JSON.parse(fs.readFileSync(path.join(here, "fixtures/gm_sheet/scratch_library_rows.fixture.json"), "utf8"));
const notesGearShapes = JSON.parse(fs.readFileSync(path.join(here, "fixtures/gm_sheet/notes_gear_shapes.fixture.json"), "utf8"));

const COMPLETE_SURFACE_IDS = [
  "overview_core_stats", "leveling", "background", "paths_subpaths", "spheres_talents", "insights",
  "actions", "forged_techniques", "manuals_recorded_arts", "immortal_arts",
  "foundation", "method", "companions", "equipment", "resources_states_suppression", "dao_i_ching", "diagnostics",
];
// Owner review 2026-09-23 (9dd09f72): GM Guidance is its own tab, placed just
// before Diagnostics; the mechanics surfaces keep their order and identity.
const OWNER_SHEET_TAB_IDS = [...COMPLETE_SURFACE_IDS.slice(0, -1), "gm_guidance", "diagnostics"];

// dbc75023 mirrors every tab into the left rail as role="presentation" copies;
// the hidden horizontal strip stays the one accessible tablist. Read the
// canonical list from the strip, not from every [data-gm-tab] in the sheet.
function canonicalTabIds(host) {
  return Array.from(host.querySelector(".gm-tabstrip").querySelectorAll("[data-gm-tab]")).map(button => button.dataset.gmTab);
}
function railTabIds(host) {
  return Array.from(host.querySelector(".owner-rail-tabs").querySelectorAll("[data-gm-tab]")).map(button => button.dataset.gmTab);
}

function completeCharacterEnvelope(available = true) {
  const action = {
    action_id: "action.cinder-touch",
    display_name: "Cinder Touch",
    action_type: "Technique",
    capability_status: "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
    timing: "Action",
    cost: "1 RES_CP",
    range: "60 feet",
    target: "One creature",
    roll_save_check: "Cultivation attack vs. Guard",
    effect: {text: "Deal 1d8 fire damage", malicious_receipt: {secret: "hide-me"}},
    failure: "No damage on a successful save",
    duration: "Instantaneous",
    limit: "Once per turn",
    counterplay: "Move out of range or succeed on the save",
    resource_costs: [{resource_id: "RES_CP", amount: 1}],
    resource_gains: [],
    resource_requirements: [{resource_id: "RES_CP", minimum: 1}],
    state_arrays: [{state_id: "burning", duration: "1 round"}],
    full_description: "A controlled touch of clean fire.",
    signature_loadout_record_ids: ["action.cinder-touch"],
    unexpected_receipt: {token: "hide-me"},
  };
  const surfaceData = {
    overview_core_stats: {
      identity: {display_name: "Wayfinder", title: "Cinder Heart", concept: "A patient fire", realm: "Mortal", cultivation_level: 5, path: "Qi Cultivation", subpath: "Cinder Heart"},
      core_stats: {armor_class: {value: 14}, hit_points: {maximum: 22, build_state_current: 22}, initiative: {bonus: 2}, speed: {walking_ft: 30}, primary_resource: {name: "RES_CP", maximum: 3}},
      metadata: {request_sha256: "hide-me"},
    },
    leveling: {levels: Array.from({length: 20}, (_, index) => ({
      cl: index + 1,
      realm: index < 15 ? "Mortal" : "Nascent Soul",
      hp: {max_after_level: 9 + index},
      pb: 2 + Math.floor(index / 4),
      ability_scores_after: {STR: 15, CON: 13},
      earned_feature_occurrences: index === 3
        ? [{occurrence_id: "asi-occurrence-4", event_id: "level-event-4", display_name: "Ability Score Improvement", acquired_at_character_cl: 4, acquired_at_path_level: 4, attainment_event: {event_id: "path-attainment-4", kind: "level_advance", sequence: 4}, acquisition_event: {event_id: "path-acquisition-4", kind: "path_acquisition", sequence: 3}, selection: {choice_kind: "ability_score_change", deltas: {CHA: 1, CON: 1}, ability_scores_after: {CHA: 11, CON: 12}, event: {event_id: "choice-event-4", kind: "ability_score_change", packet_id: "choice-packet-4", sequence: 5, target_cl: 4}}}]
        : index === 7
          ? [{occurrence_id: "insight-occurrence-8", event_id: "insight-event-8", display_name: "Read the Ash", acquired_at_character_cl: 8, acquired_at_path_level: 8, attainment_event: {event_id: "path-attainment-8", kind: "level_advance", sequence: 8}, effect: {text: "Read the ash without changing the score."}, selection: {choice_kind: "cultivation_insight_acquisition", ability: "CHA", amount: 1, event: {event_id: "choice-event-8", kind: "cultivation_insight_acquisition", packet_id: "choice-packet-8", sequence: 9, target_cl: 8}, insight_occurrence: {record_id: "insight.awakener-of-tools", acquisition_cl: 8, ability: "CHA", amount: 1, repeat_index: 1, content_binding: {pack_id: "fixture-pack", pack_hash: "fixture-pack-hash", pack_version: "1", record_hash: "fixture-record-hash"}, execution_authority: {execution_status: "display_only", manual_runtime_boundary: "Manual review required"}, source_evidence: [{source_id: "insight-source", source_hash: "fixture-source-hash"}]}}}]
          : [],
      trained_choices: index === 3 ? [{choice_id: "choice-4", display_name: "Awakener of Tools"}] : [],
    }))},
    background: {background_origin: {background: {name: "Street Urchin", summary: "Knows the back alleys.", skill_proficiencies: ["Stealth"]}, origin_insight: {name: "Orphaned", summary: "Reads people quickly."}}},
    paths_subpaths: {paths_subpaths: {
      paths: [{display_name: "Qi Cultivation", summary: "Shape internal qi.", path_level: 10}],
      subpaths: [{display_name: "Cinder Heart", summary: "Clean fire discipline.", path_level: 8}],
      earned_feature_occurrences: [
        {occurrence_id: "path-occurrence-iron-fist-1", event_id: "path-event-3", display_name: "Iron Fist", owning_path_name: "Body Refining", acquired_at_character_cl: 3, acquired_at_path_level: 3, required_path_level: 3, acquisition_cl: 3, attainment_event: {event_id: "path-attainment-3", sequence: 30}, full_description: "1d8 + STR or CON; choose the ability for attack and damage.\nB/P/S damage type is chosen at acquisition."},
        {occurrence_id: "path-occurrence-iron-fist-2", event_id: "path-event-4", display_name: "Iron Fist", owning_path_name: "Body Refining", acquired_at_character_cl: 4, acquired_at_path_level: 4, required_path_level: 4, acquisition_cl: 4, attainment_event: {event_id: "path-attainment-4", sequence: 40}, full_description: "Repeated source occurrence; the mechanical feature does not stack. Literal <script>ignored()</script> remains text."},
        {occurrence_id: "path-occurrence-guard", event_id: "path-event-10", display_name: "Bone Guard Manifestation", owning_path_name: "Body Refining", acquired_at_character_cl: 10, acquired_at_path_level: 10, required_path_level: 10, acquisition_cl: 10, attainment_event: {event_id: "path-attainment-10", sequence: 100}, action: {bone_strike: "Bone Strike", guard_the_sovereign: "Guard the Sovereign"}},
      ],
    }},
    spheres_talents: {spheres: [{display_name: "Beastmastery", one_line_description: "Understand companion instincts."}], learned_talents: [{display_name: "Cinder Touch", one_line_description: "A controlled fire touch.", timing_or_category: "Technique"}]},
    insights: {insights: [
      {insight_id: "insight-read-ash", display_name: "Read the Ash", summary: "Notice what remains after change.", gained_at_cl: 8, ability: "WIS", amount: 1, ability_change_applied: true, repeat_index: 0, source_record_hash: "insight-record-8", source_packet_ids: ["packet-8"], manual_runtime_boundary: "Display-only; no automatic execution."},
      {insight_id: "insight-read-ash", display_name: "Read the Ash", summary: "Notice what remains after change.", gained_at_cl: 12, ability: "WIS", amount: 1, ability_change_applied: true, repeat_index: 1, source_record_hash: "insight-record-12", source_packet_ids: ["packet-12"], manual_runtime_boundary: "Display-only; no automatic execution."},
    ], coverage: {available: 2, required: 2}},
    actions: {status: "ACTION_SURFACE_READY", global_combat_readiness: true, mechanical_authority: true, signature_loadout_record_ids: ["action.cinder-touch"], actions: [action], provenance: {secret: "hide-me"}},
    composite_playbooks: {
      execution_authority: false,
      classification: "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
      composites: [{
        playbook_id: "playbook.cinder-opening",
        display_name: "Cinder Opening",
        classification: "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
        capability_status: "INCOMPLETE_NON_EXECUTABLE",
        tactical_goal: "Create an opening without spending beyond the declared budget.",
        sequence: [{action_id: "action.cinder-touch", priority: 1, round_offset: 0, economy: "Action", preconditions: ["Target visible"]}],
        ordered_action_ids: ["gm.training.synthetic", "action.cinder-touch"],
        priorities: ["Act before the second exchange"],
        resource_budget: {resource_id: "RES_CP", amount: 1},
        branches: [{condition: "If the target saves", action_ids: ["action.cinder-touch"], fallback: "Defend"}],
        fallback: "Defend",
        dao_i_ching_hooks: [{hook: "Wait for the clear line", dao: "Restraint", i_ching: "Li"}],
        record_bindings: [{display_name: "Cinder Touch", capabilities: {gm_display: "SUPPORTED"}}],
        linked_action_record_ids: ["action.cinder-touch"],
        linked_action_details: [{action_id: "action.cinder-touch", name: "Cinder Touch", effect: "Fire damage"}],
        unexpected_receipt: {token: "hide-me"},
      }],
    },
    forged_techniques: {forged_techniques: [{record_id: "forged.cinder", display_name: "Cinder Touch", record_text: "Full forged record.\nNo provider output.", cost: {cp: 1}, mechanics: {effect: "1d8 fire damage", limit: "Once per turn"}}], none_state: {state: "none"}},
    manuals_recorded_arts: {manuals: [{display_name: "Manual of Quiet Embers", summary: "A recorded breathing form.", contents: {methods: ["Quiet breathing"], recipes: ["Ember tea"], recorded_arts: ["Returning Ember"], theory: ["Control before force"], false_routes: [], warnings: []}, source_packet_ids: ["manual-packet"]}], training_sources: [{source_id: "manual-source", display_name: "Manual of Quiet Embers", contents: {recorded_arts: ["Returning Ember"]}}], recorded_arts: [{record_id: "recorded.returning-ember", display_name: "Returning Ember", record_text: "A complete recorded art with its lineage."}]},
    immortal_arts: {immortal_arts: [{art_id: "immortal.cinder", display_name: "Cinder Art", record_text: "Complete immortal record.\nFull twelve-step source-backed construction.", factors: [{factor_id: "factor.creation", display_name: "Creation", cost: {cp: 4}}], action: {effect: "Shape a bounded ember body", target: "One constructed frame", range: "Self"}, construction: {mode: "initial_factory_materialization", outcome: "accepted_after_full_rederivation", payment: "reported_requirement_only", roll: null, training_choice_cost: 0}}], none_state: {state: "not_projected"}},
    foundation: {foundation: {display_name: "Empty Bowl Soul Anchor", state: "acquired", summary: "Hold power without grasping.", full_description: "A full source-backed foundation description."}},
    method: {method: {display_name: "Outer Court Twin-Current Primer", state: "acquired", summary: "A measured twin-current method.", full_description: "A full source-backed method description."}},
    companions: {companions: [{display_name: "Ashpaw", summary: "A watchful ember fox."}], coverage: {available: 1, required: 1}},
    equipment: {equipment: [], none_state: {state: "none"}},
    resources_states_suppression: {resources: [{name: "RES_CP", display_name: "Cultivation Points", current: 2, maximum: 3}], states: [{state_id: "burning", effect: "Fire damage over time", duration: "1 round"}], suppression: [{name: "No suppression", status: "clear"}]},
    dao_i_ching: {dao: {display_name: "Still Flame Dao", core_theme: "Refinement through restraint.", principles: ["Respect selected authority"]}, i_ching: {display_name: "Hexagram 30 · Li", core_theme: "Clarity through change.", principles: ["Keep interpretation non-mechanical"]}},
    diagnostics: {archive: {status: "VALID", member_count: 82, checksum_count: 81}, source: {kind: "candidate", finalized: false}, reports: {summary: {status: "PASS", valid: true, action_display_count: 1, composite_count: 1, issue_count: 0}}, raw_receipt: {request_sha256: "hide-me"}},
  };
  const surfaces = Object.fromEntries(COMPLETE_SURFACE_IDS.map(id => [id, {
    available,
    status: available ? "available" : "unavailable",
    data: available ? surfaceData[id] : null,
    reason: available ? null : "Verified source unavailable for this fixture.",
  }]));
  return {
    schema: "TianxiaFoundry.CompleteCharacterMechanicsEnvelope.v1",
    available,
    source_kind: available ? "candidate" : null,
    project_id: SCRATCH_ID,
    projection_id: "projection.complete-character",
    package_sha256: "a".repeat(64),
    candidate_sha256: "b".repeat(64),
    finalized: false,
    required_surface_ids: COMPLETE_SURFACE_IDS,
    surfaces,
    coverage: {required_count: COMPLETE_SURFACE_IDS.length, available_count: available ? COMPLETE_SURFACE_IDS.length : 0, missing_ids: available ? [] : COMPLETE_SURFACE_IDS, complete: available},
    reason: available ? null : "The matching mechanics source is unavailable.",
  };
}

const SCRATCH_ID = "00000000-0000-4000-8000-000000000002";

function sheetPayload() {
  return {
    schema_version: "TianxiaFoundry.OwnerCharacterSheetServiceResponse.v2",
    project_id: SCRATCH_ID,
    name: fixture.identity.display_name,
    build_status: "CHARACTER_SHEET_READY",
    plain_summary: "Character Sheet Ready. GM tactical authoring is the next step; GM export remains unavailable.",
    identity: {
      name: fixture.identity.display_name,
      title: fixture.identity.title,
      concept: fixture.identity.concept,
      current_cl: fixture.identity.cultivation_level,
      current_realm: fixture.identity.realm,
      path: fixture.identity.path,
      species: fixture.identity.species,
      key_ability: fixture.identity.key_ability,
    },
    workflow: {active_run: null, latest_run: null},
    sections: {},
    owner_character_sheet: fixture,
    provenance: {
      owner_locks: {status: "available", label: "Chosen by owner"},
      ai_blueprint: {status: "available", label: "Accepted character plan"},
      advancement_projection: {status: "available", label: "Advancement Ready"},
      character_sheet_projection: {status: "available", label: "Character Sheet Ready"},
    },
    factory_workspace: {status: "NOT_ATTEMPTED"},
    gm_export: {available: false, blockers: ["GM tactical authoring has not been attempted."], next_step: null},
    advanced_details: {projection_status: {}},
  };
}

function libraryCharacters() {
  return libraryRows.rows.map(row => ({
    ...row,
    lifecycle: {display_label: "Saved / existing"},
    build_status: row.project_id === SCRATCH_ID ? "CHARACTER_SHEET_READY" : "SAVED_DRAFT",
    plain_summary: "Open the character sheet to inspect this saved project.",
    workflow: {active_run: null, latest_run: null},
  }));
}

function flatten(el, depth = 0, omit = new Set()) {
  if (!el || depth > 14 || omit.has(el)) return "";
  let out = ` <${el.tagName || "?"} class="${el.className || ""}">`;
  if (el.textContent) out += el.textContent + "\n";
  for (const c of el.children || []) out += flatten(c, depth + 1, omit);
  return out;
}

class FakeClock {
  constructor() { this.now = 0; this.nextId = 1; this.tasks = new Map(); }
  setTimeout(fn, delay = 0) {
    const id = this.nextId++;
    this.tasks.set(id, {at: this.now + Number(delay || 0), fn});
    return id;
  }
  clearTimeout(id) { this.tasks.delete(id); }
  tick(ms) {
    const target = this.now + ms;
    while (true) {
      const due = [...this.tasks.entries()].filter(([, task]) => task.at <= target).sort((a, b) => a[1].at - b[1].at || a[0] - b[0]);
      if (!due.length) break;
      const [id, task] = due[0];
      this.tasks.delete(id);
      this.now = task.at;
      task.fn();
    }
    this.now = target;
  }
}
const clock = new FakeClock();
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
};
const flushPromises = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

// Build one shared sandbox whose api() stub each test can rewire.
const intervals = new Set();
after(() => { for (const timer of intervals) clearInterval(timer); });
const sandbox = {
  console,
  setTimeout: clock.setTimeout.bind(clock),
  clearTimeout: clock.clearTimeout.bind(clock),
  setInterval(fn, delay) {
    const timer = setInterval(fn, delay);
    intervals.add(timer);
    return timer;
  },
  clearInterval(timer) { clearInterval(timer); intervals.delete(timer); },
  AbortController,
  // Keep the portrait's real image-probe path executable without network I/O.
  // No load event means no saved token; the renderer retains its initials.
  Image: class { constructor() { this.src = ""; } },
  // Production budget for the optional /api/characters enrichment. The stub
  // must use it, not a shortened value, or the late-success race below can
  // never be exercised.
  __TIANXIA_LIBRARY_ENRICHMENT_TIMEOUT_MS__: 5000,
  fetch: async () => { throw new Error("network disabled in renderer gate"); },
  Option: class {
    constructor(text = "", value = "") { this.textContent = text; this.value = value; this.selected = false; this.disabled = false; }
  },
  location: {assign() {}, reload() {}},
  navigator: {userAgent: "renderer-gate"},
  document: documentStub,
  localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.addEventListener = () => {};
sandbox.removeEventListener = () => {};
vm.createContext(sandbox);
for (const file of ["sphere_talent_logic.js", "sheet_view_model.js", "complete_request_save.js", "character_search.js"]) {
  vm.runInContext(readStatic(file), sandbox, {filename: file});
}
// The permissive stub does not parse HTML select options; seed the one option
// read by the existing manual-lineage initializer before loading app.js.
documentStub.getElementById("guidedManualLineageTrainingTypes").options = [{selected: false}];
vm.runInContext(readStatic("app.js"), sandbox, {filename: "app.js"});

test("app.js top-level wiring executes under the DOM stub", () => {
  assert.equal(typeof sandbox.renderOwnerSheet, "function");
  assert.equal(typeof sandbox.renderCharacterLibrary, "function");
});

test("in-place library updates preserve deferred-delete controls and disclosures", () => {
  const character = {...libraryCharacters()[0], lifecycle: {persistence_state: "saved_draft"}};
  const card = sandbox.gmCreateCharacterLibraryCard(character);
  const main = card.querySelector(".card-main");
  const advanced = card.querySelector(".character-card-advanced");
  advanced.open = true;
  assert.match(flatten(card), /Delete permanently/);
  assert.equal(main.getAttribute("role"), "button");
  const queued = {...character, deletion_status: "queued", deletion_reason: "Hidden until restart"};
  assert.equal(sandbox.gmUpdateCharacterLibraryCard(card, queued), card);
  assert.equal(card.querySelector(".character-card-advanced"), advanced);
  assert.equal(advanced.open, true);
  assert.match(flatten(card), /Undo delete/);
  assert.match(flatten(card), /Hidden until restart/);
  assert.match(flatten(card), /Will be deleted when the Factory next restarts/);
  assert.doesNotMatch(flatten(card.querySelector(".character-card-actions")), /Delete permanently|Resume draft|Continue build/);
  assert.equal(main.getAttribute("role"), null);
  assert.equal(main.onclick, null);
  assert.equal(main.onkeydown, null);
  sandbox.gmUpdateCharacterLibraryCard(card, character);
  assert.equal(main.getAttribute("role"), "button");
  assert.equal(typeof main.onclick, "function");
  assert.match(flatten(card), /Delete permanently/);
  assert.doesNotMatch(flatten(card), /Undo delete|Hidden until restart/);
  assert.equal(advanced.open, true);
});

test("character search filters real library cards and clear restores them without replacing the sheet", async () => {
  const characters = libraryCharacters().slice(0, 2).map((row, index) => ({
    ...row, name: index ? "Mira" : "Shen Lihuo", display_name: index ? "Mira" : "Shen Lihuo",
  }));
  sandbox.api = url => url === "/api/character-library" ? Promise.resolve(characters) : deferred().promise;
  await sandbox.renderCharacterLibrary();
  const host = registry.get("characterCardList");
  const cards = Array.from(host.querySelectorAll("[data-character-project-id]"));
  assert.equal(cards.length, 2);
  const input = documentStub.getElementById("characterSearchInput");
  const count = documentStub.getElementById("characterSearchCount");
  const clear = documentStub.getElementById("clearCharacterSearch");
  const sheet = documentStub.getElementById("ownerCharacterSheet");
  const priorChildren = [...sheet.children];
  input.value = "LIHUO";
  input.dispatchEventOfType("input");
  assert.deepEqual(cards.map(card => card.hidden), [false, true]);
  assert.equal(count.textContent, "1 of 2 characters");
  assert.equal(clear.hidden, false);
  input.value = "missing character";
  input.dispatchEventOfType("input");
  assert.deepEqual(cards.map(card => card.hidden), [true, true]);
  assert.equal(count.textContent, "0 of 2 characters");
  assert.equal(host.querySelector(".character-search-empty").textContent, "No characters match 'missing character'");
  clear.click();
  assert.equal(input.value, "");
  assert.deepEqual(cards.map(card => card.hidden), [false, false]);
  assert.equal(count.textContent, "2 of 2 characters");
  assert.equal(clear.hidden, true);
  assert.equal(host.querySelector(".character-search-empty"), null);
  assert.equal(documentStub.activeElement, input);
  assert.deepEqual(sheet.children, priorChildren);
});

test("library cards show the finalized name with no placeholder leak", async () => {
  sandbox.api = async url => url === "/api/character-library"
    ? libraryCharacters()
    : libraryCharacters().map(row => ({...row, name: row.project_id === SCRATCH_ID ? "Wayfinder" : row.name}));
  const rows = await sandbox.renderCharacterLibrary();
  await flushPromises();
  assert.equal(rows.length, libraryRows.rows.length);
  const text = flatten(registry.get("characterCardList"));
  assert.match(text, /Wayfinder/);
  assert.doesNotMatch(text, /AI-proposed character/);
});

test("library cards render explicit saves, ordinary updates, and no invented dates", async () => {
  const rows = libraryCharacters().map(row => ({...row}));
  rows[0].updated_at = "2026-09-05T16:25:52Z";
  rows[0].lifecycle = {
    display_label: "Saved Draft",
    lifecycle_source: "owner_save_draft",
    updated_at: "2026-09-05T16:29:34Z",
  };
  rows[1].updated_at = "2026-09-05T16:25:52Z";
  rows[1].lifecycle = {display_label: "Saved / existing"};
  rows[2].updated_at = "2026-02-30T12:00:00Z";
  rows[2].lifecycle = {display_label: "Saved / existing"};
  sandbox.api = async url => rows;
  await sandbox.renderCharacterLibrary();
  await flushPromises();
  const details = Array.from(registry.get("characterCardList")
    .querySelectorAll(".character-library-card"))
    .map(card => card.querySelector(".character-card-detail")?.textContent || "");
  assert.match(details[0], /^Saved \S/);
  assert.match(details[1], /^Last updated \S/);
  assert.doesNotMatch(details[2], /^Last updated /);
});

test("saved pre-run cards resume the selected project without starting a build", async () => {
  const draftId = "701f2361-52da-4100-9918-eaa2dc2ea5ef";
  const lifecycle = {
    persistence_state: "saved_draft",
    is_temporary: false,
    display_label: "Saved Draft",
    plain_explanation: "This character draft is retained for later.",
    lifecycle_source: "owner_save_draft",
  };
  const characters = [{
    project_id: draftId,
    name: "AI-proposed character",
    lifecycle,
    build_status: "stage_1",
    plain_summary: "Saved draft.",
    workflow: {active: false, active_run: null, latest_run: null},
  }];
  const project = {
    project_id: draftId,
    working_name: "AI-proposed character",
    status: "stage_1",
    revision: 1,
    builder_persistence_state: "saved_draft",
    character_creation_run_count: 0,
    builder_lifecycle: lifecycle,
  };
  const calls = [];
  sandbox.api = async (url, options = {}) => {
    calls.push({url, options});
    if (url === "/api/character-library") return characters;
    if (url === "/api/characters") return [];
    if (url === "/api/projects") return [project];
    if (url === `/api/projects/${draftId}`) return {
      project: {
        project_id: draftId,
        user_locks: [
          {field: "character.identity.display_name", value: null},
          {field: "concept", value: "A patient fire"},
          {field: "target_cl", value: 15},
          {field: "power_band", value: "rival/boss"},
        ],
      },
      builder_lifecycle: lifecycle,
    };
    if (url === `/api/projects/${draftId}/character-creation/preference`) return {execution_mode: "MANUAL_CHAT"};
    throw new Error(`unexpected API call: ${url}`);
  };

  documentStub.getElementById("builderAI").scrollIntoView = () => {};
  await sandbox.renderCharacterLibrary();
  await flushPromises();
  const card = registry.get("characterCardList").querySelector(`[data-character-project-id="${draftId}"]`);
  const resume = card.querySelector(".character-card-actions").children.find(button => button.textContent === "Resume draft");
  assert.ok(resume, "saved pre-run cards expose Resume draft");
  resume.click();
  for (let attempt = 0; attempt < 4; attempt += 1) await flushPromises();

  assert.equal(registry.get("guidedName").value, "", "a null display-name lock stays blank");
  assert.equal(registry.get("guidedConcept").value, "A patient fire");
  assert.equal(registry.get("guidedLevel").value, "15");
  assert.equal(registry.get("guidedPower").value, "rival/boss");
  assert.equal(registry.get("guidedPersistenceLabel").textContent, "Saved Draft");
  assert.equal(registry.get("builderAI").hidden, false, "resume opens the build mode step");
  assert.equal(calls.some(({options}) => options.method && options.method !== "GET"), false, "resume uses reads only");
  assert.equal(calls.some(({url}) => url.includes("character-builder/projects") || url.includes("character-creation/runs")), false, "resume does not create or start a run");
});

test("owner sheet renders identity, stable mechanics tabs, utility guidance, and closed technical data", () => {
  sandbox.renderOwnerSheet(sheetPayload());
  const host = registry.get("ownerCharacterSheet");
  const dump = flatten(host);
  for (const expected of [
    "gm-sheet-header", "Wayfinder", "CL 1", "Mortal Realm", "Qi Cultivation",
    "Outer Court Twin-Current Primer", "Empty Bowl Soul Anchor",
    "GM guidance only", "GM authoring has not been prepared", "Advanced / Developer",
  ]) {
    assert.ok(dump.includes(expected), `missing from rendered sheet: ${expected}`);
  }
  const advIdx = dump.indexOf("Advanced / Developer");
  for (const banned of ["owner_locks", "projection_id", "event_head_hash"]) {
    assert.ok(!dump.slice(0, advIdx).includes(banned), `${banned} visible before Advanced`);
  }
  assert.deepEqual(canonicalTabIds(host), OWNER_SHEET_TAB_IDS);
  // The rail is a presentation copy of the same list (dbc75023), never a second tablist.
  assert.deepEqual(railTabIds(host), OWNER_SHEET_TAB_IDS);
  assert.ok(Array.from(host.querySelector(".owner-rail-tabs").querySelectorAll("[data-gm-tab]")).every(b => b.getAttribute("role") === "presentation"));
  // 9dd09f72 (owner review 2026-09-23) replaced the below-sheet utility with one GM Guidance tab.
  assert.equal(Array.from(host.querySelector(".gm-tabstrip").querySelectorAll('[data-gm-tab="gm_guidance"]')).length, 1, "GM Guidance is one tab");
  assert.equal(host.querySelector('[data-gm-utility="gm_guidance"]'), null, "the retired utility is not rendered as well");
  const guidancePanel = host.querySelector('[data-gm-panel="gm_guidance"]');
  assert.ok(guidancePanel, "GM Guidance tab has its panel");
  assert.equal(guidancePanel.dataset.completeSurface, undefined, "GM Guidance is not a mechanics surface");
  assert.match(flatten(guidancePanel), /GM guidance only/);
  assert.equal(Array.from(host.querySelectorAll("[data-gm-panel]")).length, OWNER_SHEET_TAB_IDS.length);
  assert.deepEqual(Array.from(host.querySelectorAll("[data-complete-surface]")).map(p => p.dataset.completeSurface), COMPLETE_SURFACE_IDS,
    "the mechanics surfaces keep their order");
});

test("complete-character envelope renders every canonical surface and curated mechanics", () => {
  const payload = sheetPayload();
  payload.complete_character = completeCharacterEnvelope();
  assert.match(readStatic("app.js"), /Array\.from\(badges\.children\)\.some/);
  sandbox.renderOwnerSheet(payload);
  const host = registry.get("ownerCharacterSheet");
  const markers = Array.from(host.querySelectorAll("[data-complete-surface]"));
  assert.equal(markers.length, COMPLETE_SURFACE_IDS.length);
  assert.deepEqual(markers.map(section => section.dataset.completeSurface), COMPLETE_SURFACE_IDS);
  // 80fee3e0 (owner GM-Screen rebuild, 2026-09-13) gives every tab human cards
  // plus one closed "Technical: sources, hashes and provenance" disclosure that
  // holds the source-shaped rendering and raw surface data. The same commit
  // retired the Overview verified-source summary
  // card, so that wording is no longer expected. Content may sit in either
  // place before Advanced; IDs, hashes and receipts must stay out of the human
  // cards, and every Technical disclosure must start closed.
  const technical = Array.from(host.querySelectorAll(".owner-technical"));
  assert.equal(technical.length, COMPLETE_SURFACE_IDS.length, "one Technical disclosure per mechanics surface");
  assert.ok(technical.every(details => !details.open), "Technical disclosures start closed");
  const primary = flatten(host).split("Advanced / Developer")[0];
  const human = flatten(host, 0, new Set(technical)).split("Advanced / Developer")[0];
  for (const expected of [
    "Cinder Touch", "Roll / save / check",
    "Resource costs", "States", "Signature loadout", "Global combat readiness",
    "Empty Bowl Soul Anchor", "Outer Court Twin-Current Primer",
    "Manual of Quiet Embers", "Returning Ember", "Full forged record.", "Complete immortal record.",
    "Bone Guard Manifestation", "Bone Strike", "Guard the Sovereign", "Still Flame Dao", "Hexagram 30",
  ]) assert.match(primary, new RegExp(expected), `missing complete-character content: ${expected}`);
  assert.doesNotMatch(human, /hide-me|request_sha256|candidate_sha256|raw_receipt|Execute|Spend|playbook\.cinder-opening|action\.cinder-touch/);
  // Synthetic training IDs stay out of every curated rendering; only the
  // verbatim "Raw verified surface data" dump inside Technical may carry them.
  const rawDumps = technical.flatMap(details => Array.from(details.querySelectorAll(".developer-diagnostics")));
  const curated = flatten(host, 0, new Set(rawDumps)).split("Advanced / Developer")[0];
  assert.doesNotMatch(curated, /gm\.training/);
  assert.equal((primary.match(/Iron Fist/g) || []).length >= 2, true, "same-name occurrences retain separate cards");
  assert.match(primary, /1d8 \+ STR or CON/);
  assert.match(primary, /Literal <script>ignored\(\)<\/script> remains text/);
  assert.equal(Array.from(host.querySelectorAll("script")).length, 0, "record text is inserted as textContent");
  assert.equal((primary.match(/CL 20/g) || []).length >= 1, true, "all twenty level rows are rendered");
  assert.match(primary, /Training Choice Cost: 0/);
  assert.match(primary, /Choice Kind: ability_score_change/);
  assert.match(primary, /Acquired at character CL: 3/);
  assert.match(primary, /Ability change applied: Yes/);
  assert.match(primary, /Manual review required/);
  assert.ok(!primary.includes("Cinder Opening"), "legacy composite data is ignored by the sheet");
  assert.deepEqual(canonicalTabIds(host), OWNER_SHEET_TAB_IDS);
  assert.equal(Array.from(host.querySelectorAll('[data-gm-tab="complete_character"]')).length, 0, "the old nested Complete Character tab is gone");
  assert.equal(registry.get("gmExportCharacter").disabled, true, "complete display must retain export gate wiring");
});

test("manual aliases collapse by stable record/source identity while distinct events remain", () => {
  const payload = sheetPayload();
  payload.complete_character = completeCharacterEnvelope();
  const manual = {record_id: "manual.air-returning", source_id: "source.manual.air", record_hash: "manual-hash", event_id: "manual-event", display_name: "Air Returning School"};
  const recorded = [
    {record_id: "recorded.airless-step", source_id: "source.recorded.airless", source_record_hash: "recorded-hash-1", event_id: "recorded-event-1", display_name: "Airless Step", record_text: "Airless Step source record."},
    {record_id: "recorded.returning-breath", source_id: "source.recorded.breath", source_record_hash: "recorded-hash-2", event_id: "recorded-event-2", display_name: "Returning Breath", record_text: "Returning Breath source record."},
    {record_id: "recorded.ash-memory", source_id: "source.recorded.ash", source_record_hash: "recorded-hash-3", event_id: "recorded-event-3", display_name: "Ash Memory", record_text: "Ash Memory source record."},
  ];
  const distinctOccurrence = {...recorded[0], event_id: "recorded-event-1-later", acquisition_cl: 12, record_text: "The same source record was acquired again at a distinct event."};
  const syntheticProjectTraining = Array.from({length: 14}, (_, index) => ({
    record_id: `gm.training.project.${index + 1}`,
    source_id: `gm.training.project.${index + 1}`,
    type: "other",
    display_name: `GM Project Training ${index + 1}`,
    record_text: "Guidance-only project training; grants no mechanics.",
  }));
  payload.complete_character.surfaces.manuals_recorded_arts.data = {
    "Manual_Lineage_Record.json": {manuals: [manual], recorded_arts: recorded},
    "Tianxia_Owner_Character_Sheet_v1.json": {
      manuals: [{...manual}],
      training_sources: [{source_id: manual.source_id, record_hash: manual.record_hash, display_name: manual.display_name}],
      manual_lineage: [{...manual}, ...syntheticProjectTraining],
      recorded_arts: recorded.map(row => ({...row})).concat(distinctOccurrence),
    },
  };
  sandbox.renderOwnerSheet(payload);
  const host = registry.get("ownerCharacterSheet");
  const nav = host.querySelector(".gm-tabstrip");
  const manuals = Array.from(host.querySelectorAll("[data-gm-tab]")).find(button => button.dataset.gmTab === "manuals_recorded_arts");
  nav.dispatchEventOfType("click", {target: manuals});
  const panel = host.querySelector('[data-gm-panel="manuals_recorded_arts"]');
  // Since 80fee3e0 the tab's closed Technical disclosure repeats each source
  // row as evidence and prints the raw surface data (synthetic rows included),
  // so count and read only the human cards.
  assert.ok(!panel.querySelector(".owner-technical").open, "Technical evidence starts closed");
  const content = panel.querySelector(".owner-sheet-content");
  const cards = Array.from(content.querySelectorAll(".gm-complete-record-card"));
  assert.equal(cards.length, 5, "three recorded arts and one manual alias collapse, while a distinct event remains");
  assert.equal(cards.filter(card => card.dataset.eventId !== "recorded-event-1-later").length, 4, "the three recorded arts and one manual remain after synthetic rows are filtered");
  assert.equal(cards.filter(card => card.dataset.eventId === "recorded-event-1-later").length, 1);
  assert.equal(cards.filter(card => card.dataset.eventId === "recorded-event-1").length, 1);
  const panelText = flatten(content);
  assert.doesNotMatch(panelText, /gm\.training\.project\./);
  assert.doesNotMatch(panelText, /GM Project Training/);
});

test("player-facing manuals retain distinct art acquisitions and collapse source aliases", () => {
  const payload = sheetPayload();
  payload.complete_character = completeCharacterEnvelope();
  const manual = {record_id: "manual.returning", display_name: "Returning School"};
  const first = {
    record_id: "recorded.returning", display_name: "Returning Breath",
    parent_manual_record_id: manual.record_id, event_id: "learned-first", acquisition_cl: 4,
    record_text: "Return to a steady breath.",
  };
  const later = {...first, event_id: "learned-later", acquisition_cl: 12};
  const other = {...first, record_id: "recorded.other", event_id: "learned-other"};
  for (const wrapped of [true, false]) {
    const data = {manuals: [{...manual, recorded_arts: [first]}], recorded_arts: [first, later, other]};
    payload.complete_character.surfaces.manuals_recorded_arts.data = wrapped
      ? {"Manual_Lineage_Record.json": data, "Owner_Character_Sheet.json": {recorded_arts: [{...first}, {...later}]}}
      : data;
    payload.table_manuals = [{...manual, recorded_arts: [{...first}, {...later}]}];
    sandbox.renderOwnerSheet(payload);
    const panel = registry.get("ownerCharacterSheet").querySelector('[data-gm-panel="manuals_recorded_arts"]');
    // Technical disclosures deliberately carry separate source evidence.
    const content = panel.querySelector(".owner-sheet-content");
    const cards = Array.from(content.querySelectorAll(".owner-sheet-record-card"));
    assert.equal(cards.length, 4, `${wrapped ? "wrapped" : "direct"} data: one manual and three acquisitions`);
    for (const eventId of ["learned-first", "learned-later", "learned-other"]) {
      assert.equal(cards.filter(card => card.dataset.eventId === eventId).length, 1, `${eventId} appears once`);
    }
    const rows = sandbox.ownerManualRows(sandbox.ownerSheetContext(payload));
    assert.equal(rows.artsByParent.get(manual.record_id).length, 3, "manual teaching links retain each acquisition");
    assert.equal(panel.querySelector(".owner-technical").open || false, false);
  }
});

test("Recorded Arts with different records remain distinct at the same event and level", () => {
  const payload = sheetPayload();
  payload.complete_character = completeCharacterEnvelope();
  const manual = {record_id: "manual.shared-event", display_name: "Shared Event Manual"};
  const arts = [
    {record_id: "recorded.first", display_name: "First Art", parent_manual_record_id: manual.record_id, event_id: "learned-together", acquisition_cl: 4, record_text: "First art."},
    {record_id: "recorded.second", display_name: "Second Art", parent_manual_record_id: manual.record_id, event_id: "learned-together", acquisition_cl: 4, record_text: "Second art."},
  ];
  payload.complete_character.surfaces.manuals_recorded_arts.data = {manuals: [manual], recorded_arts: arts};
  sandbox.renderOwnerSheet(payload);
  const panel = registry.get("ownerCharacterSheet").querySelector('[data-gm-panel="manuals_recorded_arts"]');
  const cards = Array.from(panel.querySelector(".owner-sheet-content").querySelectorAll(".owner-sheet-record-card"));
  assert.equal(cards.length, 3, "the Manual and both separately identified arts render");
  for (const id of ["recorded.first", "recorded.second"]) {
    assert.equal(cards.filter(card => card.dataset.occurrenceId === id).length, 1, `${id} remains visible`);
  }
});

test("Recorded Art aliases collapse when optional source provenance differs or is missing", () => {
  const payload = sheetPayload();
  payload.complete_character = completeCharacterEnvelope();
  const manual = {record_id: "manual.partial-provenance", display_name: "Partial Provenance Manual"};
  const acquisition = {record_id: "recorded.same", display_name: "Same Art", parent_manual_record_id: manual.record_id, event_id: "learned-once", acquisition_cl: 4, record_text: "One acquisition."};
  const packetAlias = {...acquisition, source_packet_ids: ["packet-a"]};
  const partialAlias = {...acquisition, event_id: undefined, source_packet_ids: undefined};
  payload.complete_character.surfaces.manuals_recorded_arts.data = {
    manuals: [{...manual, recorded_arts: [acquisition]}],
    recorded_arts: [packetAlias, partialAlias],
  };
  sandbox.renderOwnerSheet(payload);
  const panel = registry.get("ownerCharacterSheet").querySelector('[data-gm-panel="manuals_recorded_arts"]');
  const cards = Array.from(panel.querySelector(".owner-sheet-content").querySelectorAll(".owner-sheet-record-card"));
  assert.equal(cards.length, 2, "the Manual and one merged acquisition render");
  assert.equal(cards.filter(card => card.dataset.occurrenceId === "recorded.same").length, 1);
});

test("insight runtime boundary joins only one exact Path occurrence", () => {
  const standalone = {
    insight_id: "insight.boundary",
    display_name: "Boundary Insight",
    gained_at_cl: 8,
    ability: "CHA",
    amount: 1,
    ability_change_applied: true,
    source_record_hash: "boundary-record-hash",
    source_packet_ids: ["boundary-packet"],
  };
  const nested = {
    record_id: standalone.insight_id,
    event_id: "boundary-choice-event",
    acquisition_cl: standalone.gained_at_cl,
    content_binding: {record_hash: standalone.source_record_hash},
    execution_authority: {manual_runtime_boundary: "Manual review required for the selected Path choice."},
  };
  const parent = (overrides = {}) => ({
    occurrence_id: "path-boundary-occurrence",
    display_name: "Boundary Path choice",
    acquired_at_character_cl: 8,
    source_packet_ids: ["boundary-packet"],
    selection: {
      event: {event_id: "boundary-choice-event", packet_id: "boundary-packet"},
      insight_occurrence: {...nested},
    },
    ...overrides,
  });
  const payloadFor = pathRows => {
    const payload = sheetPayload();
    payload.complete_character = completeCharacterEnvelope();
    payload.complete_character.surfaces.insights.data = {"Insights.json": {insights: [standalone]}};
    payload.complete_character.surfaces.paths_subpaths.data = {"Paths.json": {earned_feature_occurrences: pathRows}};
    return payload;
  };
  const openInsights = payload => {
    sandbox.renderOwnerSheet(payload);
    const host = registry.get("ownerCharacterSheet");
    const nav = host.querySelector(".gm-tabstrip");
    const insights = Array.from(host.querySelectorAll("[data-gm-tab]")).find(button => button.dataset.gmTab === "insights");
    nav.dispatchEventOfType("click", {target: insights});
    return host.querySelector('[data-gm-panel="insights"]');
  };

  let panel = openInsights(payloadFor([parent()]));
  let panelText = flatten(panel);
  assert.match(panelText, /Related Path acquisition boundary: Manual review required for the selected Path choice\./);
  assert.match(panelText, /Boundary Insight/);
  assert.match(panelText, /Gained at CL: 8/);

  const mismatched = {...nested, content_binding: {record_hash: "different-record-hash"}};
  panel = openInsights(payloadFor([parent({selection: {
    event: {event_id: "boundary-choice-event", packet_id: "boundary-packet"},
    insight_occurrence: mismatched,
  }})]));
  panelText = flatten(panel);
  assert.match(panelText, /Execution boundary not supplied for this occurrence\./);
  assert.doesNotMatch(panelText, /Related Path acquisition boundary:/);

  panel = openInsights(payloadFor([parent(), parent({occurrence_id: "path-boundary-occurrence-2"})]));
  panelText = flatten(panel);
  assert.match(panelText, /Execution boundary not supplied for this occurrence\./);
  assert.doesNotMatch(panelText, /Related Path acquisition boundary:/);

  const conflictingBoundary = parent({selection: {
    event: {event_id: "boundary-choice-event", packet_id: "boundary-packet"},
    insight_occurrence: {
      ...nested,
      execution_authority: {manual_runtime_boundary: "A different boundary for the same occurrence."},
    },
  }});
  panel = openInsights(payloadFor([parent(), conflictingBoundary]));
  panelText = flatten(panel);
  assert.match(panelText, /Execution boundary not supplied for this occurrence\./);
  assert.doesNotMatch(panelText, /Related Path acquisition boundary:/);
});

test("insight list aliases collapse while a later occurrence remains visible", () => {
  const payload = sheetPayload();
  payload.complete_character = completeCharacterEnvelope();
  const first = {
    insight_id: "insight.alias",
    display_name: "Alias Insight",
    gained_at_cl: 8,
    ability: "CHA",
    amount: 1,
    ability_change_applied: true,
    repeat_index: 0,
    source_record_hash: "alias-record-hash-8",
    source_packet_ids: ["alias-packet-8"],
    event_id: "alias-event-8",
  };
  const later = {
    ...first,
    gained_at_cl: 12,
    repeat_index: 1,
    source_record_hash: "alias-record-hash-12",
    source_packet_ids: ["alias-packet-12"],
    event_id: "alias-event-12",
  };
  payload.complete_character.surfaces.insights.data = {
    "Character_Master_Ledger.json": {
      insights: [first],
      cultivation_insight_occurrences: [first, later],
    },
    "Insight_Projection.json": {insights: [first, later]},
    "Owner_Character_Sheet.json": {insight_occurrences: [first, later]},
  };
  sandbox.renderOwnerSheet(payload);
  const host = registry.get("ownerCharacterSheet");
  const nav = host.querySelector(".gm-tabstrip");
  const insights = Array.from(host.querySelectorAll("[data-gm-tab]")).find(button => button.dataset.gmTab === "insights");
  nav.dispatchEventOfType("click", {target: insights});
  const panel = host.querySelector('[data-gm-panel="insights"]');
  // Since 80fee3e0 the closed Technical disclosure repeats the source rows as
  // evidence; count only the human cards.
  const content = panel.querySelector(".owner-sheet-content");
  const cards = Array.from(content.querySelectorAll(".gm-complete-record-card"));
  assert.equal(cards.length, 2, "duplicate ledger/projection/sheet lists collapse while both acquisitions remain");
  // Each card is one acquisition and carries that acquisition's identity, not
  // the shared Insight record's (which named the CL 8 event on both cards).
  assert.equal(cards.filter(card => card.dataset.characterLevel === "8").length, 1);
  assert.equal(cards.filter(card => card.dataset.characterLevel === "12").length, 1);
  assert.deepEqual(cards.map(card => card.dataset.eventId), ["alias-event-8", "alias-event-12"]);
  assert.match(flatten(content), /Milestone CL 8/);
  assert.match(flatten(content), /Milestone CL 12/);
  assert.match(flatten(panel), /Gained at CL: 8/);
  assert.match(flatten(panel), /Gained at CL: 12/);
});

test("resource tab renders every wrapped pool once with saved zero and maximum values", () => {
  const payload = sheetPayload();
  payload.complete_character = completeCharacterEnvelope();
  const model = {equipment_resources_states: {resources: {qi_maximum: {
    name: "Resonance", maximum: 36, build_state_current: 2,
    current_state_note: "Saved creation values.",
    definitions: [
      {resource_id: "tianxia.resource.resonance", name: "Resonance", current: 2, max: 36},
      {resource_id: "tianxia.resource.stamina", name: "Stamina", current: 0, max: 36},
    ],
  }}}};
  payload.complete_character.surfaces.resources_states_suppression.data = {
    "Tianxia_GM_Character_Model_v1.json": model,
    "Tianxia_GM_Character_View_Model_v2.json": structuredClone(model),
  };
  sandbox.renderOwnerSheet(payload);
  const host = registry.get("ownerCharacterSheet");
  const nav = host.querySelector(".gm-tabstrip");
  const tab = Array.from(host.querySelectorAll("[data-gm-tab]")).find(button => button.dataset.gmTab === "resources_states_suppression");
  nav.dispatchEventOfType("click", {target: tab});
  const panel = host.querySelector('[data-gm-panel="resources_states_suppression"]');
  const cards = Array.from(panel.querySelectorAll(".gm-complete-record-card"));
  assert.equal(cards.length, 2);
  const stamina = cards.find(card => card.dataset.resourceId === "tianxia.resource.stamina");
  const resonance = cards.find(card => card.dataset.resourceId === "tianxia.resource.resonance");
  assert.match(flatten(stamina), /Stamina.*Saved current: 0.*Maximum: 36/s);
  assert.match(flatten(resonance), /Resonance.*Saved current: 2.*Maximum: 36/s);
  assert.match(flatten(panel), /Saved creation values/);
});

test("unavailable complete-character envelope is honest without hiding the base sheet", () => {
  const payload = sheetPayload();
  payload.complete_character = completeCharacterEnvelope(false);
  sandbox.renderOwnerSheet(payload);
  const host = registry.get("ownerCharacterSheet");
  // 80fee3e0 retired the Overview "Verified source ... 0/18 verified source
  // sections" card; each tab now states its own unavailability instead.
  const panels = Array.from(host.querySelectorAll("[data-complete-surface]"));
  assert.equal(panels.length, COMPLETE_SURFACE_IDS.length);
  for (const panel of panels) {
    const notice = panel.querySelector(".gm-complete-unavailable");
    assert.ok(notice, `${panel.dataset.completeSurface} says it is unavailable`);
    assert.equal(notice.textContent, "Verified source unavailable for this fixture.");
  }
  assert.match(flatten(host), /Wayfinder/);
  const railStats = flatten(host.querySelector(".owner-rail-stats"));
  assert.match(railStats, /Armor Class/, "the base sheet's quick stats stay visible");
  assert.equal(registry.get("gmExportCharacter").disabled, true);
});



test("GM Guidance renders bounded Dao, I Ching, training, and advanced-art states without legacy playbooks", () => {
  const payload = sheetPayload();
  payload.gm_authoring_view = {
    available: true,
    authority: {classification: "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY", mechanical_authority: false},
    dao_i_ching: {
      dao: {display_name: "Still Flame Dao", core_theme: "Refinement through restraint.", principles: ["Respect selected authority"], mechanical_effects: []},
      i_ching: {display_name: "Hexagram 30 · Li", core_theme: "Clarity through change.", principles: ["Keep interpretation non-mechanical"], mechanical_effects: []},
    },
    composite_playbooks: [{display_name: "Old archived playbook"}],
    training_sources: [{display_name: "Outer Court Notes", summary: "Source-backed context only."}],
    advanced_systems: {
      forged_techniques: {state: "none"},
      recorded_arts: {state: "none"},
      immortal_arts: {state: "not_projected", note: "Separate end-game system."},
    },
  };
  sandbox.renderOwnerSheet(payload);
  const dump = flatten(registry.get("ownerCharacterSheet"));
  for (const expected of [
    "Still Flame Dao", "Hexagram 30",
    "Outer Court Notes", "Forged Techniques", "Recorded Arts", "Immortal Arts",
    "not a combat macro", "grant no action, bonus, resource change, legality, or execution authority",
  ]) assert.ok(dump.includes(expected), `missing GM Guidance content: ${expected}`);
  assert.ok(!dump.includes("Old archived playbook"), "legacy archived playbook data is ignored by the renderer");
});

test("tab strip activates exactly one panel", () => {
  const host = registry.get("ownerCharacterSheet");
  const nav = host.querySelector(".gm-tabstrip");
  const pathsBtn = Array.from(host.querySelectorAll("[data-gm-tab]")).find(b => b.dataset.gmTab === "paths_subpaths");
  nav.dispatchEventOfType("click", {target: pathsBtn}); // real browsers bubble to the nav listener
  const active = Array.from(host.querySelectorAll("[data-gm-panel]")).filter(p => p.classList.contains("active")).map(p => p.dataset.gmPanel);
  assert.deepEqual(active, ["paths_subpaths"]);
});

test("needs-attention state renders banner with recovery jump", () => {
  const payload = sheetPayload();
  payload.workflow = {active_run: {run_id: "cg1.run.x", status: "NEEDS_REVIEW", blockers: [{title: "Review required", message: "Choose a name."}], next_legal_action: "Resolve the saved owner decision."}, latest_run: null};
  sandbox.renderOwnerSheet(payload);
  const dump = flatten(registry.get("ownerCharacterSheet"));
  assert.match(dump, /needs your attention/);
  assert.match(dump, /Resolve in the builder/);
});


test("primary library success paints while optional enrichment remains pending forever", async () => {
  const enrichment = deferred();
  sandbox.api = url => url === "/api/character-library" ? Promise.resolve(libraryCharacters()) : enrichment.promise;
  const rows = await sandbox.renderCharacterLibrary();
  assert.equal(rows.length, libraryRows.rows.length);
  const host = registry.get("characterCardList");
  assert.equal(Array.from(host.querySelectorAll(".character-library-card")).length, libraryRows.rows.length);
  assert.doesNotMatch(flatten(host), /Loading saved characters/);
});

test("optional enrichment rejection is nonfatal and disclosed only as developer detail", async () => {
  sandbox.api = url => url === "/api/character-library"
    ? Promise.resolve(libraryCharacters())
    : Promise.reject(new Error("optional enrichment offline"));
  await sandbox.renderCharacterLibrary();
  await flushPromises();
  const host = registry.get("characterCardList");
  assert.equal(Array.from(host.querySelectorAll(".character-library-card")).length, libraryRows.rows.length);
  assert.ok(host.querySelector(".gm-library-enrichment-diagnostic"));
  assert.match(flatten(host), /optional enrichment offline/);
});

test("optional enrichment times out on a fake clock without delaying first paint", async () => {
  const enrichment = deferred();
  sandbox.api = url => url === "/api/character-library" ? Promise.resolve(libraryCharacters()) : enrichment.promise;
  await sandbox.renderCharacterLibrary();
  assert.equal(registry.get("characterCardList").querySelectorAll(".character-library-card").length, libraryRows.rows.length);
  clock.tick(4999);
  await flushPromises();
  assert.doesNotMatch(flatten(registry.get("characterCardList")), /timed out/);
  clock.tick(1);
  await flushPromises();
  assert.match(flatten(registry.get("characterCardList")), /timed out after 5000 ms/);
});

test("pending cards automatically receive completed facts and order despite enrichment failure", async () => {
  const complete = libraryCharacters().slice(0, 2).map((row, i) => ({
    ...row, name: `Finished ${i}`, path: "Sword", target_cl: 7, summary_pending: false,
  })).reverse();
  const partial = complete.slice().reverse().map(row => ({...row, name: "", path: null, target_cl: null, summary_pending: true}));
  let requests = 0;
  sandbox.api = url => {
    if (url !== "/api/character-library") return Promise.reject(new Error("optional offline"));
    requests += 1;
    if (requests === 2) return Promise.reject(new Error("temporary poll failure"));
    return Promise.resolve(requests === 1 ? partial : complete);
  };
  await sandbox.renderCharacterLibrary();
  await flushPromises();
  const host = registry.get("characterCardList");
  assert.equal(Array.from(host.querySelectorAll(".character-library-card")).length, 2);
  assert.match(flatten(host), /Character details are loading/);
  clock.tick(1000);
  await flushPromises();
  assert.equal(Array.from(host.querySelectorAll(".character-library-card")).length, 2, "poll errors retain partial cards");
  clock.tick(2000);
  await flushPromises();
  const cards = Array.from(host.querySelectorAll(".character-library-card"));
  assert.deepEqual(cards.map(card => card.dataset.characterProjectId), complete.map(row => row.project_id));
  assert.deepEqual(cards.map(card => card.querySelector(".character-card-name").textContent), complete.map(row => row.name));
  assert.match(flatten(host), /Sword/);
  assert.match(flatten(host), /Target CL 7/);
  assert.doesNotMatch(flatten(host), /Character details are loading/);
  clock.tick(10000);
  await flushPromises();
  assert.equal(requests, 3, "polling stops when summaries are complete");
});

test("enrichment that lands after a summary completes cannot undo the refreshed summary", async () => {
  // The production shape of the race: /api/characters is read before an
  // acceptance lands, the acceptance completes the summary and advances the
  // source version, and the slow read finally returns inside its 5 s budget.
  const enrichment = deferred();
  const pending = libraryCharacters().slice(0, 2).map(row => ({
    ...row, name: "", path: null, target_cl: null, summary_pending: true, source_revision: 7,
  }));
  const completed = pending.map((row, index) => ({
    ...row, name: `Accepted Name ${index}`, path: "Sword", target_cl: 7,
    summary_pending: false, source_revision: 8,
  })).reverse();
  let requests = 0;
  sandbox.api = url => {
    if (url !== "/api/character-library") return enrichment.promise;
    requests += 1;
    return Promise.resolve(requests === 1 ? pending : completed);
  };
  await sandbox.renderCharacterLibrary();
  const host = registry.get("characterCardList");
  assert.match(flatten(host), /Character details are loading/);
  clock.tick(1000);
  await flushPromises();
  assert.doesNotMatch(flatten(host), /Character details are loading/, "the summary completed");
  assert.match(flatten(host), /Accepted Name 0/);
  // The pre-completion read finally returns, still inside the production budget.
  clock.tick(3000);
  enrichment.resolve(pending.map(row => ({...row, name: "Stale Accepted Name", source_revision: 7})));
  await flushPromises();
  const text = flatten(host);
  assert.match(text, /Accepted Name 0/, "the completed summary stays on the card");
  assert.doesNotMatch(text, /Stale Accepted Name/, "an older read never overwrites a refreshed summary");
  assert.doesNotMatch(text, /Character details are loading/);
});

test("enrichment from the current source version still updates the card", async () => {
  const enrichment = deferred();
  const rows = libraryCharacters().slice(0, 2).map(row => ({...row, source_revision: 9}));
  sandbox.api = url => url === "/api/character-library" ? Promise.resolve(rows) : enrichment.promise;
  await sandbox.renderCharacterLibrary();
  enrichment.resolve(rows.map(row => ({...row, name: "Current Source Name"})));
  await flushPromises();
  assert.match(flatten(registry.get("characterCardList")), /Current Source Name/);
});

test("an unchanged automatic poll keeps the focused control, scroll position and opened details", async () => {
  const pending = libraryCharacters().slice(0, 2).map(row => ({
    ...row, name: "", path: null, target_cl: null, summary_pending: true,
  }));
  let requests = 0;
  sandbox.api = url => {
    if (url !== "/api/character-library") return Promise.reject(new Error("optional offline"));
    requests += 1;
    return Promise.resolve(pending);
  };
  await sandbox.renderCharacterLibrary();
  const host = registry.get("characterCardList");
  const card = Array.from(host.querySelectorAll("[data-character-project-id]")).find(row => row.dataset.characterProjectId === SCRATCH_ID);
  const main = card.querySelector(".card-main");
  card.querySelector(".character-card-advanced").open = true;
  host.scrollTop = 64;
  main.focus();
  for (const step of [1000, 2000, 4000]) { clock.tick(step); await flushPromises(); }
  assert.ok(requests >= 4, `the pending summary was polled repeatedly, saw ${requests} requests`);
  const sameCard = Array.from(host.querySelectorAll("[data-character-project-id]")).find(row => row.dataset.characterProjectId === SCRATCH_ID);
  assert.equal(sameCard, card, "an unchanged poll must not replace the card");
  assert.equal(documentStub.activeElement, main, "keyboard focus survives automatic polls");
  assert.equal(sameCard.querySelector(".character-card-advanced").open, true, "an opened disclosure is not collapsed");
  assert.equal(host.scrollTop, 64, "scroll position survives automatic polls");
});

test("a completing, reordering poll keeps the focused control and opened details", async () => {
  const pending = libraryCharacters().slice(0, 2).map(row => ({
    ...row, name: "", path: null, target_cl: null, summary_pending: true,
  }));
  const completed = pending.map((row, index) => ({
    ...row, name: `Finished ${index}`, path: "Sword", target_cl: 7, summary_pending: false,
  })).reverse();
  let requests = 0;
  sandbox.api = url => {
    if (url !== "/api/character-library") return Promise.reject(new Error("optional offline"));
    requests += 1;
    return Promise.resolve(requests === 1 ? pending : completed);
  };
  await sandbox.renderCharacterLibrary();
  const host = registry.get("characterCardList");
  const card = Array.from(host.querySelectorAll("[data-character-project-id]")).find(row => row.dataset.characterProjectId === SCRATCH_ID);
  card.querySelector(".character-card-advanced").open = true;
  card.querySelector(".card-main").focus();
  clock.tick(1000);
  await flushPromises();
  const after = Array.from(host.querySelectorAll(".character-library-card"));
  assert.deepEqual(after.map(row => row.dataset.characterProjectId), completed.map(row => row.project_id), "the completed order is applied");
  const sameCard = after.find(row => row.dataset.characterProjectId === SCRATCH_ID);
  assert.equal(sameCard, card, "the card element is reused across a completing poll");
  assert.equal(sameCard.querySelector(".character-card-advanced").open, true, "the opened disclosure is not collapsed");
  assert.equal(documentStub.activeElement, card.querySelector(".card-main"), "focus survives a completing, reordering poll");
  assert.equal(after.filter(row => row.dataset.characterProjectId === SCRATCH_ID).length, 1, "reordering does not duplicate a card");
  assert.match(flatten(host), /Sword/);
});

// The stub's selector matcher only understands ids, classes and data attributes,
// so the disclosure's summary is reached the way the renderer reaches it: by tag.
function advancedSummaryOf(card) {
  const details = card.querySelector(".character-card-advanced");
  return details.children.find(node => node.tagName === "SUMMARY");
}

test("a browser-shaped NodeList paints the library and a completing poll", async () => {
  // A browser answers querySelectorAll with a NodeList, which has no .map(),
  // and the stub now answers the same way. Treating a query result as an Array
  // throws here exactly as it did on the first paint in a browser, where every
  // nonempty library failed to render and was reported as a library error.
  const probe = documentStub.getElementById("characterCardList").querySelectorAll(".character-library-card");
  assert.equal(Array.isArray(probe), false, "the stub must hand the renderer a NodeList, not an Array");
  assert.equal(typeof probe.map, "undefined", "a NodeList has no .map(), so an Array-only call is caught here");
  assert.equal(typeof probe.length, "number", "a NodeList is sized");
  assert.deepEqual([...probe], Array.from(probe), "a NodeList spreads and iterates");

  const pending = libraryCharacters().slice(0, 2).map(row => ({
    ...row, name: "", path: null, target_cl: null, summary_pending: true,
  }));
  const completed = pending.map((row, index) => ({
    ...row, name: `Completed ${index}`, path: "Sword", target_cl: 7, summary_pending: false,
  })).reverse();
  let requests = 0;
  sandbox.api = url => {
    if (url !== "/api/character-library") return Promise.reject(new Error("optional offline"));
    requests += 1;
    return Promise.resolve(requests === 1 ? pending : completed);
  };
  await assert.doesNotReject(
    () => sandbox.renderCharacterLibrary(),
    "a nonempty library must paint from a browser NodeList instead of failing as a library error",
  );
  const host = registry.get("characterCardList");
  assert.equal(Array.from(host.querySelectorAll(".character-library-card")).length, 2, "both cards are rendered");
  assert.doesNotMatch(flatten(host), /could not be loaded/);
  clock.tick(1000);
  await flushPromises();
  assert.deepEqual(
    Array.from(host.querySelectorAll(".character-library-card"), card => card.dataset.characterProjectId),
    completed.map(row => row.project_id),
    "a completing poll reconciles and reorders from a browser NodeList too",
  );
  assert.match(flatten(host), /Sword/);
});

test("an open, focused Advanced details survives unchanged and reordering polls", async () => {
  // The player-facing shape: the owner tabs to "Advanced details" on a card
  // while its details are still filling, and the background repaint must not
  // take that keyboard focus or collapse the disclosure underneath them.
  const pending = libraryCharacters().slice(0, 2).map(row => ({
    ...row, name: "", path: null, target_cl: null, summary_pending: true,
  }));
  const completed = pending.map((row, index) => ({
    ...row, name: `Finished ${index}`, path: "Sword", target_cl: 7, summary_pending: false,
  })).reverse();
  let requests = 0;
  let complete = false;
  sandbox.api = url => {
    if (url !== "/api/character-library") return Promise.reject(new Error("optional offline"));
    requests += 1;
    // Polls keep returning the same still-filling rows until the flag flips, so
    // the owner is left with an unchanged list for several repaints.
    return Promise.resolve(complete ? completed : pending);
  };
  await sandbox.renderCharacterLibrary();
  const host = registry.get("characterCardList");
  const card = Array.from(host.querySelectorAll("[data-character-project-id]")).find(row => row.dataset.characterProjectId === SCRATCH_ID);
  assert.equal(host.children[1], card, "the card to focus starts second, so reversing the list moves it with insertBefore");
  const details = card.querySelector(".character-card-advanced");
  details.open = true;
  const summary = advancedSummaryOf(card);
  summary.focus();
  assert.equal(documentStub.activeElement, summary, "the disclosure summary takes the keyboard");

  for (const step of [1000, 2000, 4000]) { clock.tick(step); await flushPromises(); }
  assert.ok(requests >= 4, `the pending summary was polled repeatedly, saw ${requests} requests`);
  assert.equal(documentStub.activeElement, summary, "an unchanged poll leaves focus on the Advanced details summary");
  assert.equal(card.querySelector(".character-card-advanced").open, true, "an unchanged poll leaves the disclosure open");
  assert.equal(card.querySelector(".character-card-name").textContent, "Unnamed character in progress", "the card is still awaiting its details, so the list is genuinely unchanged");

  // Move the focused card itself: ordinary insertBefore loses focus before
  // reconciliation restores it. Moving only its neighbour would hide the bug.
  const insertBefore = host.insertBefore;
  let movedFocusedCard = false;
  let focusAfterMove = summary;
  host.insertBefore = function(node, reference) {
    const result = insertBefore.call(this, node, reference);
    if (node === card) {
      movedFocusedCard = true;
      focusAfterMove = documentStub.activeElement;
    }
    return result;
  };
  complete = true;
  try {
    clock.tick(5000);
    await flushPromises();
  } finally {
    host.insertBefore = insertBefore;
  }
  assert.equal(movedFocusedCard, true, "reconciliation actually moved the focused subtree");
  assert.equal(focusAfterMove, null, "the ordinary DOM move drops focus before restoration");
  const after = Array.from(host.querySelectorAll(".character-library-card"));
  assert.deepEqual(after.map(row => row.dataset.characterProjectId), completed.map(row => row.project_id), "the completing poll reordered the cards");
  const sameCard = after.find(row => row.dataset.characterProjectId === SCRATCH_ID);
  assert.equal(sameCard, card, "the focused card element is reused across the reorder");
  assert.equal(sameCard.querySelector(".character-card-advanced").open, true, "a reordering poll leaves the disclosure open");
  assert.equal(documentStub.activeElement, summary, "a reordering poll leaves focus on the Advanced details summary");
  assert.equal(summary.textContent, "Advanced details", "the focused summary is still the one the owner was reading");
});

test("late enrichment updates cards in place without losing focus, scroll, or active sheet tab", async () => {
  const enrichment = deferred();
  sandbox.api = url => url === "/api/character-library" ? Promise.resolve(libraryCharacters()) : enrichment.promise;
  await sandbox.renderCharacterLibrary();
  const host = registry.get("characterCardList");
  const card = Array.from(host.querySelectorAll("[data-character-project-id]")).find(row => row.dataset.characterProjectId === SCRATCH_ID);
  const main = card.querySelector(".card-main");
  host.scrollTop = 73;
  main.focus();
  sandbox.renderOwnerSheet(sheetPayload());
  const sheetHost = registry.get("ownerCharacterSheet");
  const nav = sheetHost.querySelector(".gm-tabstrip");
  const paths = Array.from(sheetHost.querySelectorAll("[data-gm-tab]")).find(button => button.dataset.gmTab === "paths_subpaths");
  nav.dispatchEventOfType("click", {target: paths});

  enrichment.resolve(libraryCharacters().map(row => ({...row, name: row.project_id === SCRATCH_ID ? "Scratch Late" : row.name})));
  await flushPromises();

  const sameCard = Array.from(host.querySelectorAll("[data-character-project-id]")).find(row => row.dataset.characterProjectId === SCRATCH_ID);
  assert.equal(sameCard, card);
  assert.equal(host.scrollTop, 73);
  assert.equal(documentStub.activeElement, main);
  assert.equal(sameCard.querySelector(".character-card-name").textContent, "Scratch Late");
  assert.deepEqual(Array.from(sheetHost.querySelectorAll("[data-gm-panel]")).filter(panel => panel.classList.contains("active")).map(panel => panel.dataset.gmPanel), ["paths_subpaths"]);
});

test("a stale prior enrichment response cannot overwrite a newer retry", async () => {
  const oldEnrichment = deferred();
  let round = 1;
  sandbox.api = url => {
    if (url === "/api/character-library") return Promise.resolve(libraryCharacters());
    if (round === 1) return oldEnrichment.promise;
    return Promise.resolve(libraryCharacters().map(row => ({...row, name: row.project_id === SCRATCH_ID ? "Newer Name" : row.name})));
  };
  await sandbox.renderCharacterLibrary();
  round = 2;
  await sandbox.renderCharacterLibrary();
  await flushPromises();
  oldEnrichment.resolve(libraryCharacters().map(row => ({...row, name: row.project_id === SCRATCH_ID ? "Stale Wrong Name" : row.name})));
  await flushPromises();
  const text = flatten(registry.get("characterCardList"));
  assert.match(text, /Newer Name/);
  assert.doesNotMatch(text, /Stale Wrong Name/);
});

test("primary failure shows retry and a successful retry restores cards", async () => {
  let primaryAttempts = 0;
  sandbox.api = url => {
    if (url === "/api/character-library") {
      primaryAttempts += 1;
      return primaryAttempts === 1 ? Promise.reject(new Error("primary unavailable")) : Promise.resolve(libraryCharacters());
    }
    return deferred().promise;
  };
  await assert.rejects(() => sandbox.renderCharacterLibrary(), /primary unavailable/);
  const host = registry.get("characterCardList");
  assert.match(flatten(host), /Saved characters could not be loaded/);
  const retry = host.querySelector(".gm-library-retry");
  assert.ok(retry, "primary failure must expose retry");
  retry.click();
  await flushPromises();
  assert.equal(primaryAttempts, 2);
  assert.equal(Array.from(host.querySelectorAll(".character-library-card")).length, libraryRows.rows.length);
});

test("legacy Notes & Gear shapes do not reintroduce a retired primary tab or leak technical fields", () => {
  for (const [shape, snapshot] of Object.entries(notesGearShapes)) {
    const payload = sheetPayload();
    payload.owner_character_sheet = snapshot;
    sandbox.renderOwnerSheet(payload);
    const host = registry.get("ownerCharacterSheet");
    assert.deepEqual(canonicalTabIds(host), OWNER_SHEET_TAB_IDS, `${shape} stable tab list`);
    assert.equal(Array.from(host.querySelectorAll('[data-gm-tab="notes_gear"]')).length, 0, `${shape} retired tab`);
    const primary = flatten(host).split("Advanced / Developer")[0];
    assert.doesNotMatch(primary, /item\.raw\.only|receipt_hash/, `${shape} technical data leaked`);
  }
});

test("opening a library character loads its Cultivation panel", async () => {
  const calls = [];
  const project = {
    project: {
      name: "Wayfinder",
      revision: 1,
      content_lock: {catalog_build_id: "fixture"},
      user_locks: [],
    },
  };
  const authorityStatus = {
    status: "READY",
    method_count: 1,
    orthodox_foundation_count: 1,
    operative_pairwise_authority_rows: 1,
  };
  sandbox.api = async url => {
    calls.push(url);
    if (url === "/api/character-library") return libraryCharacters();
    if (url === "/api/characters") return [];
    if (url === `/api/characters/${SCRATCH_ID}/sheet`) return sheetPayload();
    if (url === `/api/characters/${SCRATCH_ID}/factory-workspace/view`) return {available: false};
    if (url === `/api/characters/${SCRATCH_ID}/factory-workspace/final-character/preview`) return {available: false};
    if (url === `/api/projects/${SCRATCH_ID}`) return project;
    if (url === `/api/projects/${SCRATCH_ID}/character-creation/preference`) return {};
    if (url === `/api/projects/${SCRATCH_ID}/read-models`) return {};
    if (url === `/api/projects/${SCRATCH_ID}/stage1/status`) return {project_id: SCRATCH_ID, project_revision: 1};
    if (url === `/api/projects/${SCRATCH_ID}/stage2/status`) return {artifacts: []};
    if (url === "/api/non-sphere/authority/status") return authorityStatus;
    if (url === "/api/non-sphere/paths") return {records: []};
    if (url === "/api/non-sphere/foundations") return {orthodox: []};
    if (url === `/api/non-sphere/projects/${SCRATCH_ID}/state`) return {
      access_source_records: [], primary_method_id: null, foundation_id: null, paths: [], target_cl: 5,
    };
    if (url === `/api/non-sphere/methods?project_id=${SCRATCH_ID}`) return {records: []};
    if (url === `/api/non-sphere/projects/${SCRATCH_ID}/readiness`) return {ready: false, blockers: []};
    if (url === `/api/non-sphere/projects/${SCRATCH_ID}/ap-eligibility`) return {paths: []};
    if (url === `/api/non-sphere/projects/${SCRATCH_ID}/evidence`) return {evidence: []};
    return {};
  };
  await sandbox.renderCharacterLibrary();
  const card = registry.get("characterCardList").querySelector(`[data-character-project-id="${SCRATCH_ID}"]`);
  await card.querySelector(".card-main").onclick();
  await flushPromises();
  assert.ok(calls.includes(`/api/non-sphere/projects/${SCRATCH_ID}/state`));
  assert.match(registry.get("nonSphereAuthorityStatus").textContent, /READY/);
});

test("a slow Cultivation response for a prior selection cannot replace the current panel", async () => {
  const stale = deferred();
  const stalePayload = {
    access_source_records: [], primary_method_id: null, foundation_id: null, paths: [], target_cl: 5,
    records: [], ready: false, blockers: [{message: "stale project"}], evidence: [],
  };
  sandbox.api = async url => {
    if (url.includes("project-a")) return stale.promise;
    if (url.includes("project-b") && url.endsWith("/readiness")) return {ready: true, blockers: []};
    if (url.includes("project-b") && url.endsWith("/state")) return {
      access_source_records: [], primary_method_id: null, foundation_id: null, paths: [], target_cl: 5,
    };
    if (url.includes("project-b") && url.endsWith("/ap-eligibility")) return {paths: []};
    if (url.includes("project-b") && url.endsWith("/evidence")) return {evidence: []};
    if (url.includes("project-b") && url.includes("/methods?")) return {records: []};
    return {};
  };
  vm.runInContext("selectedProject = 'project-a'", sandbox);
  const staleLoad = sandbox.loadNonSphereAuthorityPanel("project-a");
  await flushPromises();
  vm.runInContext("selectedProject = 'project-b'", sandbox);
  await sandbox.loadNonSphereAuthorityPanel("project-b");
  assert.match(registry.get("nonSphereReadiness").textContent, /ready for this character/i);
  stale.resolve(stalePayload);
  await staleLoad;
  await flushPromises();
  assert.match(registry.get("nonSphereReadiness").textContent, /ready for this character/i);
  assert.doesNotMatch(registry.get("nonSphereTechnical").textContent, /stale project/);
});

function nonSpherePanelState(projectId) {
  return {
    access_source_records: [],
    primary_method_id: null,
    foundation_id: null,
    paths: [],
    target_cl: 5,
    project_id: projectId,
  };
}

function nonSpherePanelApi(url, projectId, {post = null, state = null} = {}) {
  if (url === "/api/non-sphere/authority/status") return {status: "READY", method_count: 1, orthodox_foundation_count: 1, operative_pairwise_authority_rows: 1};
  if (url === "/api/non-sphere/paths") return {records: []};
  if (url === "/api/non-sphere/foundations") return {orthodox: []};
  if (url === `/api/non-sphere/projects/${projectId}/state`) return state || nonSpherePanelState(projectId);
  if (url === `/api/non-sphere/methods?project_id=${projectId}`) return {records: [{method_id: `method-${projectId}`, name: "Bounded Method", disposition: {state: "known", selectable_as_primary: true}}]};
  if (url === `/api/non-sphere/projects/${projectId}/readiness`) return {ready: true, blockers: []};
  if (url === `/api/non-sphere/projects/${projectId}/ap-eligibility`) return {paths: []};
  if (url === `/api/non-sphere/projects/${projectId}/evidence`) return {evidence: []};
  if (post && url === `/api/non-sphere/projects/${projectId}/primary-method`) return post;
  return {};
}

test("a late Cultivation action result cannot overwrite the current project panel", async () => {
  const late = deferred();
  const calls = [];
  sandbox.api = async url => {
    calls.push(url);
    if (url === "/api/non-sphere/projects/project-a/primary-method") return late.promise;
    return nonSpherePanelApi(url, url.includes("project-b") ? "project-b" : "project-a", {post: {project_id: "project-b", status: "saved-b"}});
  };
  vm.runInContext("selectedProject = 'project-a'; nonSphereCatalogCache = null", sandbox);
  await sandbox.loadNonSphereAuthorityPanel("project-a");
  registry.get("nonSpherePrimaryMethod").value = "method-project-a";
  registry.get("setNonSpherePrimaryMethod").onclick();
  assert.ok(calls.includes("/api/non-sphere/projects/project-a/primary-method"));

  vm.runInContext("selectedProject = 'project-b'", sandbox);
  await sandbox.loadNonSphereAuthorityPanel("project-b");
  assert.match(registry.get("nonSphereAuthorityStatus").textContent, /READY/);
  late.resolve({project_id: "project-a", status: "late-a-success"});
  await flushPromises();
  assert.doesNotMatch(registry.get("nonSphereTechnical").textContent, /late-a-success/);
  assert.match(registry.get("nonSphereTechnical").textContent, /project-b/);
});

test("a late rejected Cultivation action cannot overwrite the current project panel", async () => {
  const late = deferred();
  const calls = [];
  sandbox.api = async url => {
    calls.push(url);
    if (url === "/api/non-sphere/projects/project-a/primary-method") return late.promise;
    return nonSpherePanelApi(url, url.includes("project-b") ? "project-b" : "project-a", {post: {project_id: "project-b", status: "saved-b"}});
  };
  vm.runInContext("selectedProject = 'project-a'; nonSphereCatalogCache = null", sandbox);
  await sandbox.loadNonSphereAuthorityPanel("project-a");
  registry.get("nonSpherePrimaryMethod").value = "method-project-a";
  registry.get("setNonSpherePrimaryMethod").onclick();
  assert.ok(calls.includes("/api/non-sphere/projects/project-a/primary-method"));

  vm.runInContext("selectedProject = 'project-b'", sandbox);
  await sandbox.loadNonSphereAuthorityPanel("project-b");
  const beforeLateFailure = registry.get("nonSphereTechnical").textContent;
  assert.match(beforeLateFailure, /project-b/);
  late.reject(new Error("late-a-failure"));
  await flushPromises();
  assert.equal(registry.get("nonSphereTechnical").textContent, beforeLateFailure);
  assert.doesNotMatch(registry.get("nonSphereTechnical").textContent, /late-a-failure/);
});

test("stale Cultivation controls are rejected before posting to a newer project", async () => {
  const bState = deferred();
  const calls = [];
  sandbox.api = async url => {
    calls.push(url);
    if (url === "/api/non-sphere/projects/project-b/state") return bState.promise;
    return nonSpherePanelApi(url, url.includes("project-b") ? "project-b" : "project-a", {post: {project_id: "project-b", status: "saved-b"}});
  };
  vm.runInContext("selectedProject = 'project-a'; nonSphereCatalogCache = null", sandbox);
  await sandbox.loadNonSphereAuthorityPanel("project-a");
  registry.get("nonSpherePrimaryMethod").value = "method-project-a";

  vm.runInContext("selectedProject = 'project-b'", sandbox);
  const loadingB = sandbox.loadNonSphereAuthorityPanel("project-b");
  await flushPromises();
  registry.get("setNonSpherePrimaryMethod").onclick();
  assert.equal(calls.filter(url => url.includes("/primary-method")).length, 0, "A's control cannot post while B is loading");
  assert.match(registry.get("nonSphereTechnical").textContent, /stale for the current character/i);

  bState.resolve(nonSpherePanelState("project-b"));
  await loadingB;
  registry.get("nonSpherePrimaryMethod").value = "method-project-b";
  registry.get("setNonSpherePrimaryMethod").onclick();
  await flushPromises();
  assert.ok(calls.includes("/api/non-sphere/projects/project-b/primary-method"));
  assert.doesNotMatch(calls.join("\n"), /project-a\/primary-method/);
});
