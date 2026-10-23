"""Native Training and Tools acquisition, installed-sheet reload and item replay.

All characters and durable data are generated under pytest's queued basetemp.
No model or network transport is used. The service and installed zip are real.

## Stays private
Every acquisition checks the printed Training and Tools text hash (gatherer_training._source), and the
public export scrambles that owner text, so the public run refuses every acquisition. The grow.js
assertions also read the source. This file runs only on the private side.
"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
import zipfile

import pytest

from app.models import TabletopAdvanceRequest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat import carry, table_advance
from combat.ext.gatherer_training import SOURCE, SPHERE, KIT_ID, CONTENTS, TEXT_SHA256
from combat.factory_compiler import compile_character, equipment_list
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000015"
FOE = "0badc0de-0000-4000-8000-000000000016"
OWNER = "actor:factory." + PID
PATH = "tianxia.path.qi_cultivation"
BACKGROUND = "tianxia.background.abandoned_orphan"
BONUS = "tianxia.talent.harvesting_gathering.field_ledger"


def sheet(*, trained=None, cl=1):
    return {
        "identity": {"display_name": "Gatherer", "cultivation_level": cl, "proficiency_bonus": 2,
                     "path_ids": [PATH], "key_ability": "CON"},
        "path_and_subpath": {"path_record_id": PATH, "path_record_ids": [PATH]},
        "background_origin": {"background": {"background_id": BACKGROUND}},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": key, "score": 14, "modifier": 2}
                          for key in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "armor_class": {"base_value": 12}, "hit_points": {"maximum": 30},
            "primary_resource": {"name": "Qi", "maximum": 10}, "speed": {"walking_ft": 30},
            "technique_save_dc": 12, "technique_attack_bonus": 4,
            "skills": [{"skill": trained, "bonus": 4, "proficient": True, "proficiency_multiplier": 1}]
                      if trained in {"Nature", "Survival", "Medicine"} else [],
        },
        "proficiencies": {"skills": [trained] if trained in {"Nature", "Survival", "Medicine"} else [],
                          "tools": [trained] if trained and trained not in {"Nature", "Survival", "Medicine"} else []},
        "spheres_and_talents": {"sphere_record_ids": [], "automatic_sphere_component_record_ids": [],
                               "learned_talent_record_ids": []}, "equipment": [],
    }


def install(root, document, pid=PID):
    folder = root / "portable_characters" / pid
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))


@pytest.fixture(scope="module")
def catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def services(root, catalog):
    combat = CombatService(ROOT, root)
    table = TabletopService(combat, root)
    table.canonical_catalog = catalog
    return combat, table


def acquire(table, proficiency="Nature", *, gm=False, **choices):
    # The same validated model and native caller as the public advancement API.
    request = TabletopAdvanceRequest.model_validate({"kind": "sphere", "record_id": SPHERE,
        "gm": gm, "learning": {"proficiency": proficiency, **choices}})
    return table.add_advancement(PID, request.kind, request.record_id, gm=request.gm, learning=request.learning)


def assignment(by):
    return {"by": by, "background_id": BACKGROUND, "path_id": PATH}


def test_exact_source_hash_and_inert_unselected_control(tmp_path, catalog):
    text = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[SOURCE]
    assert hashlib.sha256(text.encode()).hexdigest() == TEXT_SHA256
    base = sheet()
    install(tmp_path, base)
    combat, table = services(tmp_path, catalog)
    assert combat._factory_owner_sheet(PID) == base
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError, match="proficiency choice"):
        table.add_advancement(PID, "sphere", SPHERE)
    assert table.buttons.get(PID) == before
    assert combat._factory_owner_sheet(PID) == base
    assert not equipment_list(base)["items"]


@pytest.mark.parametrize("proficiency", ["Nature", "Survival", "Medicine", "Herbalism Kit", "Land Vehicles",
                                        "Woodcarver’s Tools", "Mason’s Tools", "Cartographer’s Tools", "Weaver’s Tools"])
def test_every_printed_proficiency_class_persists_and_compiles(tmp_path, catalog, proficiency):
    base = sheet()
    install(tmp_path, base)
    combat, table = services(tmp_path, catalog)
    artisan = proficiency not in {"Nature", "Survival", "Medicine", "Herbalism Kit", "Land Vehicles"}
    args = {"artisan_ruling": {"tool": proficiency, "reason": "This artisan tool can prepare and preserve gathered field materials."}} if artisan else {}
    acquire(table, proficiency, gm=artisan, **args)
    fresh, reopened = services(tmp_path, catalog)
    actual = fresh._factory_owner_sheet(PID)
    group = "skills" if proficiency in {"Nature", "Survival", "Medicine"} else "tools"
    assert actual["proficiencies"][group] == [proficiency]
    assert SOURCE in actual["spheres_and_talents"]["automatic_sphere_component_record_ids"]
    assert not actual["spheres_and_talents"]["learned_talent_record_ids"]
    assert not equipment_list(actual)["items"]
    assert table_advance.apply(actual, reopened.buttons.get(PID)["advancement"]) == actual
    bundle = compile_character(actual, actor_id=OWNER)
    if group == "skills":
        summary = reopened.sheet(PID)["summary"]
        assert next(row["bonus"] for row in summary["skills"] if row["skill"] == proficiency) == 4
    assert bundle["actor_id"] == OWNER
    with pytest.raises(TabletopError, match="already known|when the Sphere is learned|different learning choice"):
        acquire(reopened, proficiency, gm=artisan, **args)
    assert fresh._factory_owner_sheet(PID) == actual


@pytest.mark.parametrize("proficiency", ["Nature", "Herbalism Kit", "Land Vehicles", "Woodcarver’s Tools"])
def test_already_proficient_gets_one_mortal_bonus_without_changing_training(tmp_path, catalog, proficiency):
    base = sheet(trained=proficiency)
    install(tmp_path, base)
    combat, table = services(tmp_path, catalog)
    artisan = proficiency == "Woodcarver’s Tools"
    args = {"artisan_ruling": {"tool": proficiency, "reason": "Suitable for cutting and preparing gathered wood."}} if artisan else {}
    acquire(table, proficiency, gm=artisan, bonus_talent_id=BONUS, **args)
    fresh, reopened = services(tmp_path, catalog)
    actual = fresh._factory_owner_sheet(PID)
    assert actual["proficiencies"] == base["proficiencies"]
    assert actual["spheres_and_talents"]["learned_talent_record_ids"] == [BONUS]
    saved = reopened.buttons.get(PID)["advancement"]
    assert saved["talents"] == []  # attached to its source, no ordinary talent slot
    learning = saved["spheres"][0]["learning"]
    assert learning["already_proficient"] == 1
    assert learning["source"] == {"record_id": SOURCE, "text_sha256": TEXT_SHA256}
    assert table_advance.apply(actual, saved) == actual


@pytest.mark.parametrize("choice", [
    {}, {"bonus_talent_id": "not-a-talent"},
    {"bonus_talent_id": "tianxia.talent.harvesting_gathering.spirit_herb_appraisal"},
    {"bonus_talent_id": "TAL_ATHLETICS_WALL_STUNT"},
    {"bonus_talent_id": [BONUS, BONUS]},
])
def test_invalid_or_nonmortal_bonus_never_commits_even_with_gm_override(tmp_path, catalog, choice):
    install(tmp_path, sheet(trained="Nature", cl=10))
    combat, table = services(tmp_path, catalog)
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        acquire(table, "Nature", gm=True, **choice)
    assert table.buttons.get(PID) == before
    assert SPHERE not in combat._factory_owner_sheet(PID)["spheres_and_talents"]["sphere_record_ids"]


def test_duplicate_bonus_is_rejected(tmp_path, catalog):
    base = sheet(trained="Nature")
    base["spheres_and_talents"]["learned_talent_record_ids"] = [BONUS]
    install(tmp_path, base)
    _, table = services(tmp_path, catalog)
    with pytest.raises(TabletopError):
        acquire(table, bonus_talent_id=BONUS)


def test_later_proficiency_cannot_manufacture_a_retroactive_learning_bonus(tmp_path, catalog):
    base = sheet(trained="Nature")
    base["spheres_and_talents"]["sphere_record_ids"] = [SPHERE]
    install(tmp_path, base)
    combat, table = services(tmp_path, catalog)
    with pytest.raises(TabletopError, match="when the Sphere is learned"):
        acquire(table, gm=True, bonus_talent_id=BONUS)
    assert combat._factory_owner_sheet(PID) == base
    assert not (table.buttons.get(PID).get("advancement") or {}).get("spheres")


@pytest.mark.parametrize("gm,ruling", [(False, {"tool": "Weaver’s Tools", "reason": "Preserving field materials"}),
                                       (True, None), (True, {"tool": "Mason’s Tools", "reason": "Wrong tool"}),
                                       (True, {"tool": "Weaver’s Tools", "reason": ""})])
def test_artisan_suitability_needs_the_actual_gm_tool_decision(tmp_path, catalog, gm, ruling):
    install(tmp_path, sheet())
    _, table = services(tmp_path, catalog)
    with pytest.raises(TabletopError):
        acquire(table, "Weaver’s Tools", gm=gm, artisan_ruling=ruling)
    assert not (table.buttons.get(PID).get("advancement") or {}).get("spheres")


@pytest.mark.parametrize("choice", [None, {"equipment_assignmnt": {"by": "class"}},
                                     {"proficiency": "Nature", "bonus_talnt_id": BONUS}, "Nature"])
def test_plain_or_misspelled_learning_is_refused_and_never_silently_dropped(tmp_path, catalog, choice):
    # Plain Learn would grant no proficiency, and a later Learn is refused as retroactive; a typo must not vanish.
    install(tmp_path, sheet())
    combat, table = services(tmp_path, catalog)
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        table.add_advancement(PID, "sphere", SPHERE, learning=choice)
    assert table.buttons.get(PID) == before
    assert SPHERE not in combat._factory_owner_sheet(PID)["spheres_and_talents"]["sphere_record_ids"]


def test_table_route_serves_the_learning_menu_to_grow(tmp_path, catalog):
    install(tmp_path, sheet())
    _, table = services(tmp_path, catalog)
    [entry] = [row for row in table.advancement(PID)["source_learning"] if row["sphere_id"] == SPHERE]
    assert entry["source_id"] == SOURCE
    assert "Nature" in entry["proficiencies"] and "Herbalism Kit" in entry["proficiencies"]


def test_source_learning_hooks_are_documented_in_the_hook_list():
    doc = (ROOT / "combat/ext/__init__.py").read_text()
    for name in ("source_learning_options", "prepare_source_learning", "project_source_learning"):
        assert f"  {name}(" in doc


@pytest.mark.parametrize("by", ["class", "background"])
def test_actual_starting_assignment_delivers_one_exact_kit_cold_reload_and_item_replay(tmp_path, catalog, by):
    install(tmp_path, sheet())
    install(tmp_path, sheet(), FOE)
    combat, table = services(tmp_path, catalog)
    acquire(table, equipment_assignment=assignment(by))
    fresh, reopened = services(tmp_path, catalog)
    actual = fresh._factory_owner_sheet(PID)
    kit = actual["equipment"][0]["starting_kit"]
    [item] = [row for row in kit["items"] if row["item_id"] == KIT_ID]
    assert item["quantity"] == 1 and item["contents"] == list(CONTENTS)
    assert item["source"] == SOURCE and item["source_reference"]["text_sha256"] == TEXT_SHA256
    assert kit["background_id"] == BACKGROUND and kit["path_id"] == PATH
    assert {row["source"] for row in kit["items"]} >= {"background", "path", SOURCE}
    assert len([row for row in equipment_list(actual)["items"] if row["item_id"] == KIT_ID]) == 1
    assert table_advance.apply(actual, reopened.buttons.get(PID)["advancement"]) == actual
    # Import the acquired character through native compilation/match creation.
    other = "actor:factory." + FOE
    view = fresh.create_factory_match(project_ids=[PID], opponent_actor_ids=[other],
        control_modes={OWNER: "MANUAL", other: "MANUAL"}, match_seed="GATHERER-ITEM-" + by)
    mid = view["match_id"]
    for _ in range(2):
        state = reopened.state(mid)
        if state["menu"]["actor_id"] == OWNER:
            break
        menu = state["menu"]
        assert reopened.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    # The kit is carried by the owner and the saved match replays cleanly after a cold reload.
    # (Drop/Pick up of the kit from the action menu is not asserted here: pickup is gated by the
    # engine's 5 ft reach check, which this test does not model.)
    loaded = fresh._load_session(mid)
    actor = loaded.engine.state.actors[OWNER]
    assert carry.holds(loaded.engine, actor, KIT_ID)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("assignment_input", [True, {"by": "purchase"},
    {"by": "background", "background_id": "tianxia.background.exiled_noble", "path_id": PATH},
    {"by": "class", "background_id": BACKGROUND, "path_id": "tianxia.path.body_refining"}])
def test_no_invented_assignment_or_other_character_equipment(tmp_path, catalog, assignment_input):
    install(tmp_path, sheet())
    combat, table = services(tmp_path, catalog)
    with pytest.raises(TabletopError):
        acquire(table, equipment_assignment=assignment_input)
    assert combat._factory_owner_sheet(PID)["equipment"] == []
    assert not (table.buttons.get(PID).get("advancement") or {}).get("spheres")


def test_grow_ui_renders_the_training_choice_and_posts_it_for_a_sphere_learn():
    # Fails without the Grow wiring: a plain Learn of this Sphere was refused by the server, and the UI never offered the choice.
    js = (ROOT / "static/tabletop/grow.js").read_text(encoding="utf-8")
    assert "source_learning" in js and "trainingBlock" in js
    assert "trainingSource(add.dataset.id)" in js
    assert 'post("advancement", { kind: "sphere", record_id: d.sphere_id' in js
    assert "learning.artisan_ruling" in js and "learning.bonus_talent_id" in js
    assert "equipment_assignment" in js


def test_the_body_grow_sends_is_accepted_by_the_route_model_and_refused_when_plain(tmp_path, catalog):
    # The exact JSON shape grow.js posts for a Training and Tools Learn, through the request model the route uses.
    install(tmp_path, sheet())
    combat, table = services(tmp_path, catalog)
    body = {"kind": "sphere", "record_id": SPHERE, "gm": False, "source": "campaign",
            "learning": {"proficiency": "Nature",
                         "equipment_assignment": {"by": "class", "background_id": BACKGROUND, "path_id": PATH, "path_option": "option_a"}}}
    request = TabletopAdvanceRequest.model_validate(body)
    table.add_advancement(PID, request.kind, request.record_id, gm=request.gm, source=request.source, learning=request.learning)
    fresh, _ = services(tmp_path, catalog)
    assert SPHERE in fresh._factory_owner_sheet(PID)["spheres_and_talents"]["sphere_record_ids"]
    assert fresh._factory_owner_sheet(PID)["equipment"][0]["starting_kit"]["path_id"] == PATH
    plain = TabletopAdvanceRequest.model_validate({"kind": "sphere", "record_id": SPHERE, "gm": False, "source": "campaign"})
    with pytest.raises(TabletopError):
        table.add_advancement(PID, plain.kind, plain.record_id, gm=plain.gm, source=plain.source, learning=plain.learning)


def test_unheld_custom_tool_with_a_bonus_is_refused_and_leaves_no_row(tmp_path, catalog):
    # Grow must not offer a bonus for an unheld artisan's tool; the service refuses one even with a GM ruling.
    install(tmp_path, sheet())
    _, table = services(tmp_path, catalog)
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError, match="already have"):
        acquire(table, "Weaver’s Tools", gm=True,
                artisan_ruling={"tool": "Weaver’s Tools", "reason": "Preserving field materials"},
                bonus_talent_id=BONUS)
    assert table.buttons.get(PID) == before


def _drive_grow(menu, tmp_path, *, name, reason=None, chosen_bonus=None):
    # Runs the real grow.js in node against the service's own menu. It picks the proficiency the way the form does
    # (a typed artisan's tool goes through "Another artisan's tool"), types the GM's reason, picks a bonus only if the
    # form enables one, and presses the form's save only if the form allows it.
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to drive grow.js")
    source = (ROOT / "static/tabletop/grow.js").read_text(encoding="utf-8")
    source = source.replace("export function", "function").replace("export async function", "async function")
    select = name if name in STANDARD_PROFICIENCIES else "__other__"
    driver = tmp_path / "grow_driver.js"
    driver.write_text(GROW_DRIVER.replace("__GROW__", json.dumps(source)).replace("__MENU__", json.dumps(menu))
                      .replace("__BONUS__", json.dumps(BONUS)).replace("__SPHERE__", json.dumps(SPHERE))
                      .replace("__SELECT__", json.dumps(select)).replace("__NAME__", json.dumps(name))
                      .replace("__REASON__", json.dumps(reason)).replace("__CHOSEN_BONUS__", json.dumps(chosen_bonus)),
                      encoding="utf-8")
    result = subprocess.run([node, str(driver)], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _replay(table, body):
    # The body grow.js posted, through the request model and native caller the route uses.
    request = TabletopAdvanceRequest.model_validate({"kind": body["kind"], "record_id": body["record_id"],
                                                     "gm": body["gm"], "source": body["source"], "learning": body["learning"]})
    return table.add_advancement(PID, request.kind, request.record_id, gm=request.gm, source=request.source, learning=request.learning)


STANDARD_PROFICIENCIES = ["Nature", "Survival", "Medicine", "Herbalism Kit", "Land Vehicles"]

GROW_DRIVER = r"""
const source = __GROW__;
const menu = __MENU__;
const BONUS = __BONUS__;
const SPHERE = __SPHERE__;
const SELECT = __SELECT__;
const NAME = __NAME__;
const REASON = __REASON__;
const CHOSEN_BONUS = __CHOSEN_BONUS__;
const posts = [];
const ids = {"grow-gm": {checked: true}};
const root = {children: [], addEventListener() {}, replaceChildren(...c) { this.children = c; }};
ids["grow-root"] = root;
// Every render builds fresh elements; the latest one per data attribute is what the form shows now.
const latest = {};
function h(tag, attrs, ...children) {
  const value = {tag, ...(attrs || {}), children: children.flat(Infinity).filter(c => c !== null && c !== undefined),
    addEventListener() {}, replaceChildren() {}, focus() {}, setSelectionRange() {}};
  if (attrs?.id) ids[attrs.id] = value;
  for (const [key, field] of Object.entries(attrs?.dataset || {})) latest[key + "=" + field] = value;
  return value;
}
const pause = () => new Promise(resolve => setImmediate(resolve));
// The real rerender runs (onInput reads the grow-training panel and rebuilds it through trainingBlock()). Only the
// DOM diff is stubbed: each build is recorded above, so the latest build is what the form shows.
const grow = new Function("h", "ids", "pause", "root", "posts", "menu", "BONUS", "SPHERE", "fetchFn",
  source + "\nreturn {initGrow, loadGrow, onClick, onChange, onInput, noDiff() { patchGrowNode = () => {}; }};");
const api = grow(h, ids, pause, root, posts, menu, BONUS, SPHERE, null);
(async () => {
  api.noDiff();
  api.initGrow({h, $: id => ids[id], projectId: () => "campaign", toast() {}, reloadSheet: async () => {},
    fetchJson: async (url, options) => {
      if (url === "/api/session") return {token: "synthetic"};
      if (!options) return menu;
      posts.push({url, body: JSON.parse(options.body)});
      return menu;
    }});
  await api.loadGrow();
  api.onClick({target: {closest: sel => sel === "[data-grow-add]" ? {dataset: {growAdd: "sphere", id: SPHERE}} : null}});
  api.onChange({target: {dataset: {growLearn: "proficiency"}, value: SELECT}});
  if (SELECT === "__other__") api.onInput({target: {dataset: {growLearn: "other"}, value: NAME}});
  if (REASON !== null) api.onInput({target: {dataset: {growLearn: "reason"}, value: REASON}});
  const bonus = latest["growLearn=bonus_talent_id"];
  const offered = bonus.children.map(option => option.value);
  const bonusOpen = !bonus.disabled;
  if (bonusOpen && CHOSEN_BONUS !== null) api.onChange({target: {dataset: {growLearn: "bonus_talent_id"}, value: CHOSEN_BONUS}});
  const save = latest["growLearningSave=1"];
  const canSave = !save.disabled;
  if (canSave) api.onClick({target: {closest: sel => sel === "[data-grow-learning-save]" ? {dataset: {}} : null}});
  await pause(); await pause();
  console.log(JSON.stringify({bonusOpen, offered, canSave, posts}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def test_held_custom_tool_offers_the_bonus_in_grow_and_the_offered_save_is_accepted(tmp_path, catalog):
    # Fails before the fix: the menu omitted the held "Weaver's Tools", so Grow disabled the bonus and never sent it,
    # and the native save refused the acquisition.
    base = sheet(trained="Weaver’s Tools")
    install(tmp_path, base)
    combat, table = services(tmp_path, catalog)
    menu = table.advancement(PID)
    [entry] = [row for row in menu["source_learning"] if row["sphere_id"] == SPHERE]
    assert "Weaver’s Tools" in entry["already_proficient"]
    drive = _drive_grow(menu, tmp_path, name="Weaver’s Tools", reason="Preserving field materials", chosen_bonus=BONUS)
    assert drive["bonusOpen"] is True and BONUS in drive["offered"]
    assert drive["canSave"] is True
    [post] = [p for p in drive["posts"] if p["url"].endswith("/advancement")]
    body = post["body"]
    assert body["learning"]["proficiency"] == "Weaver’s Tools" and body["learning"]["bonus_talent_id"] == BONUS
    _replay(table, body)
    fresh, reopened = services(tmp_path, catalog)
    actual = fresh._factory_owner_sheet(PID)
    assert actual["proficiencies"] == base["proficiencies"]
    assert actual["spheres_and_talents"]["learned_talent_record_ids"] == [BONUS]
    saved = reopened.buttons.get(PID)["advancement"]
    assert saved["spheres"][0]["learning"]["already_proficient"] == 1
    assert table_advance.apply(actual, saved) == actual


@pytest.mark.parametrize("name,held,reason,chosen_bonus", [
    ("Weaver’s Tools", True, "Preserving field materials", BONUS),
    ("Weaver’s Tools", False, "Preserving field materials", None),
    ("Nature", False, None, None),
    ("Nature", True, None, BONUS),
])
def test_the_offered_grow_save_is_never_refused_and_the_bonus_follows_held_proficiency(tmp_path, catalog, name, held, reason, chosen_bonus):
    # Service-level regression: whatever the form offers for a complete choice, the save it posts is accepted.
    # Fails before the fix: an unheld artisan's tool was offered a bonus the service refuses.
    install(tmp_path, sheet(trained=name if held else None))
    _, table = services(tmp_path, catalog)
    menu = table.advancement(PID)
    drive = _drive_grow(menu, tmp_path, name=name, reason=reason, chosen_bonus=chosen_bonus)
    assert drive["bonusOpen"] is held
    if held:
        assert BONUS in drive["offered"]
    assert drive["canSave"] is True
    [post] = [p for p in drive["posts"] if p["url"].endswith("/advancement")]
    assert ("bonus_talent_id" in post["body"]["learning"]) is held
    _replay(table, post["body"])
    fresh, _ = services(tmp_path, catalog)
    assert SPHERE in fresh._factory_owner_sheet(PID)["spheres_and_talents"]["sphere_record_ids"]


def test_grow_gates_the_bonus_on_held_proficiency_only_and_never_posts_an_unheld_bonus():
    # Fails before the fix: the bonus was also enabled for any custom artisan's tool (OTHER_TOOL).
    js = (ROOT / "static/tabletop/grow.js").read_text(encoding="utf-8")
    assert "const bonusOpen = alreadyHeld;" in js
    assert "|| d.proficiency === OTHER_TOOL" not in js
    assert "if (d.bonus_talent_id && heldProficiency(src, name)) learning.bonus_talent_id" in js


def test_kit_menus_list_every_choice_and_a_chosen_pick_reaches_the_kit(tmp_path, catalog):
    # Fails before the fix: the Grow form had no kit choices and always sent no picks.
    install(tmp_path, sheet())
    combat, table = services(tmp_path, catalog)
    [entry] = [row for row in table.advancement(PID)["source_learning"] if row["sphere_id"] == SPHERE]
    menus = entry["kit_menus"][PATH]
    assert menus and all(len(menu["options"]) >= 2 for menu in menus)
    picks = {menu["choice_id"]: len(menu["options"]) - 1 for menu in menus}
    acquire(table, equipment_assignment={"by": "class", "background_id": BACKGROUND, "path_id": PATH,
                                         "path_option": "option_a", "picks": picks})
    kit = combat._factory_owner_sheet(PID)["equipment"][0]["starting_kit"]
    chosen = {row["choice_id"]: row for row in kit["choices"]}
    for choice_id, index in picks.items():
        assert chosen[choice_id]["selected_index"] == index and chosen[choice_id]["fallback_used"] is False


def test_grow_renders_kit_picks_and_resets_them_per_path():
    js = (ROOT / "static/tabletop/grow.js").read_text(encoding="utf-8")
    assert "dataset: { growPick: menu.choice_id }" in js
    assert "kitMenusFor(src, d)" in js and 'if (t.dataset.growLearn === "path_id") learnDraft.picks = {}' in js
    assert "picks: Object.fromEntries(kitMenusFor(src, d)" in js
