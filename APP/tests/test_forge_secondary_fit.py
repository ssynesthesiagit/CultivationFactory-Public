"""Forge Secondary Sphere Effects: Base Form fit, Grow greying, grouping, and the GM override (FORGEFIT1).

Fit is judged by the compiler (combat.forged.secondary_fit / fit_table); the Grow page only reads the table built
at load. The Node part runs the real grow.js functions offline with stubbed DOM helpers, as the Grow tests do."""
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from combat.factory_compiler import TYPED_AUTHORITY
from combat.forged import fit_table, rules, secondary_fit, mechanic_for
from combat.table_advance import base_abilities
from character_creation.constructed_arts.forged_technique import construct_forged_technique
from character_creation.constructed_arts.forging_authority import load_forging_authority
from tests.test_grow1_abilities import PID, ROOT, growth_service, installed_sheet
from tests.test_grow1_respec_review import seal

MECHANICS = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
PRIMARY = "FIRE_TAL_FLAME_LASH"          # single-target attack on Fire
AREA = "TAL_AIR_CYCLONE_PRISON"          # save + zone over enemies_in_area (Air)
TARGET_MOVE = "ASH_TAL_ASHEN_BURIAL"   # target condition with an effect the compiler carries
SELF_MOVE = "TAL_AIR_ARROW_TURNING_BREATH"  # ally modifier extracted but dropped by Ward/Movement
GROW_JS = ROOT / "static/tabletop/grow.js"


def _talent_ids(count):
    ids = [key for key, row in MECHANICS.items() if row.get("kind") == "talent" and row.get("effects")]
    return ids[:count]


def test_weapon_form_refuses_area_and_accepts_a_target_effect():
    assert secondary_fit("strike", PRIMARY, AREA, MECHANICS)[0] is False
    assert secondary_fit("strike", PRIMARY, TARGET_MOVE, MECHANICS)[0] is True


def test_area_form_takes_the_area_effect():
    assert secondary_fit("zone", PRIMARY, AREA, MECHANICS)[0] is True
    assert secondary_fit("burst", PRIMARY, AREA, MECHANICS)[0] is True


def test_ward_refuses_hostile_effects_and_dropped_ally_modifiers():
    fits, reason = secondary_fit("ward", PRIMARY, AREA, MECHANICS)
    assert fits is False and "Ward" in reason
    fits, reason = secondary_fit("ward", PRIMARY, SELF_MOVE, MECHANICS)
    assert not fits and "drops" in reason


def test_movement_form_refuses_target_effects_and_dropped_ally_modifiers():
    fits, reason = secondary_fit("movement", PRIMARY, TARGET_MOVE, MECHANICS)
    assert fits is False and "target" in reason
    fits, reason = secondary_fit("movement", PRIMARY, SELF_MOVE, MECHANICS)
    assert not fits and "drops" in reason
    assert secondary_fit("strike", PRIMARY, "TAL_AIR_FEATHER_FALL_BREATH", MECHANICS)[0] is False
    assert secondary_fit("ward", PRIMARY, "TAL_AIR_FLOWING_STEP", MECHANICS)[0] is False


def test_same_sphere_and_unknown_form_are_refused_with_plain_words():
    assert secondary_fit("zone", PRIMARY, PRIMARY, MECHANICS) == (False, "One effect per Sphere.")
    assert secondary_fit("nope", PRIMARY, AREA, MECHANICS)[0] is False


def test_fit_list_changes_with_the_base_form():
    table = fit_table([AREA, TARGET_MOVE, SELF_MOVE], MECHANICS, rules())
    assert table["strike"][AREA][0] is False
    assert table["zone"][AREA][0] is True
    assert table["ward"][AREA][0] is False
    assert table["strike"][TARGET_MOVE][0] is True and table["movement"][TARGET_MOVE][0] is False


def test_fit_table_for_a_character_is_fast():
    # The probe scan runs once per server process (cached); a Grow load after that must stay under budget.
    ids = _talent_ids(60)
    fit_table(ids, MECHANICS, rules())
    started = time.perf_counter()
    table = fit_table(ids, MECHANICS, rules())
    elapsed = time.perf_counter() - started
    assert len(table) == len(rules()["forms"])
    assert elapsed < 0.15, elapsed


def test_advancement_payload_ships_the_fit_table_and_reuses_authority_catalog(tmp_path):
    from combat.factory_compiler import TYPED_AUTHORITY
    from combat.tabletop_service import _typed_mechanics_catalog

    seal(tmp_path, installed_sheet())
    service = growth_service(tmp_path)
    first = service.advancement(PID)
    forge = first["forge"]
    assert set(forge["fit"]) == set(rules()["forms"])
    assert isinstance(forge["sphere_complexity"], int) and forge["sphere_complexity"] >= 1
    cached = _typed_mechanics_catalog(str(TYPED_AUTHORITY), TYPED_AUTHORITY.stat().st_mtime_ns)
    assert service.advancement(PID)["forge"]["fit"] == forge["fit"]
    assert _typed_mechanics_catalog(str(TYPED_AUTHORITY), TYPED_AUTHORITY.stat().st_mtime_ns) is cached


def test_chip_click_path_makes_no_request():
    source = GROW_JS.read_text(encoding="utf-8")
    for name in ("forgeCapacity", "forgeFit", "secondaryGrey", "augmentGrey", "refreshForgeInPlace", "forgeStatus"):
        match = re.search(r"function " + name + r"\(.*?\n}\n", source, re.S)
        assert match, name
        assert "fetch(" not in match.group(0) and "post(" not in match.group(0), name
    assert "refreshForgeInPlace()" in source
    refresh = re.search(r"function refreshForgeInPlace\(\).*?\n}\n", source, re.S)
    assert refresh and 'choices.replaceChildren(...forgeChoiceRows())' in refresh.group(0)
    assert 'id: "grow-forge-choices"' in source


NODE_SCRIPT = r"""
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const fixture = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
  let source = fs.readFileSync(process.argv[2], 'utf8');
  source += '\n;globalThis.__grow = { setDeps: (v) => { deps = v; }, setData: (v) => { data = v; }, setForge: (v) => { forge = v; },' +
    ' secondaryGrey, augmentGrey, forgeFit, forgeCapacity, secondaryGroups, forgeBlock, refreshForgeInPlace, onChange };';
  global.fetch = () => { throw new Error('the chip path must not fetch'); };
  await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  const G = globalThis.__grow;
  let gmOn = false;
  const h = (tag, props, ...kids) => ({ tag, props: props || {}, children: kids.flat(Infinity).filter((x) => x !== null && x !== undefined && x !== false) });
  const domInputs = [];
  let choiceChildren = [];
  const choiceContainer = { dataset: {}, replaceChildren: (...nodes) => { choiceChildren = nodes; } };
  const statusNode = { textContent: '' };
  const root = { querySelectorAll: (s) => s === "input[data-forge-pick]" ? domInputs : [], querySelector: () => null };
  const forgeDom = (id) => id === 'grow-forge' ? root : id === 'grow-forge-choices' ? choiceContainer : id === 'grow-forge-status' ? statusNode : null;
  const text = (node) => node == null ? '' : typeof node !== 'object' ? String(node) : (node.children || []).map(text).join('');
  const walk = (node, out) => { if (node && typeof node === 'object') { out.push(node); (node.children || []).forEach((c) => walk(c, out)); } return out; };
  G.setDeps({ h, $: (id) => (id === 'grow-gm' ? { checked: gmOn } : forgeDom(id)), fetchJson: async () => { throw new Error('no fetch'); },
    toast() {}, reloadSheet() {}, projectId: 'p' });
  const forgeState = (over) => Object.assign({ name: '', base_form: 'strike', primary_talent_id: fixture.primary, secondary_talent_ids: [],
    augment_ids: [], drawback_ids: [], choices: {} }, over || {});
  G.setData({ forge: fixture.forge });
  const sphereOf = (id) => fixture.forge.sources.find((row) => row.id === id).sphere_id;
  const secondaries = fixture.candidates.filter((id) => sphereOf(id) !== sphereOf(fixture.primary));
  const bySphere = (sphere) => secondaries.filter((id) => sphereOf(id) === sphere);
  const spheres = [...new Set(secondaries.map(sphereOf))];
  const pickedFirst = bySphere(spheres[0])[0];
  const out = {};

  // Sphere limit (max_spheres 2): after one Sphere is picked, a third Sphere is greyed; the picked Sphere stays enabled.
  G.setForge(forgeState({ secondary_talent_ids: [pickedFirst] }));
  const thirdSphere = secondaries.find((id) => sphereOf(id) !== sphereOf(pickedFirst));
  out.sphereLimitGrey = G.secondaryGrey(fixture.forge, fixture.forge.sources.find((row) => row.id === thirdSphere));
  out.swapGrey = G.secondaryGrey(fixture.forge, fixture.forge.sources.find((row) => row.id === bySphere(sphereOf(pickedFirst))[1] || pickedFirst));

  // Complexity limit: a Realm maximum of 2 with Strike (1) allows exactly one secondary.
  const tight = Object.assign({}, fixture.forge, { max_complexity: 2, max_spheres: 4 });
  G.setData({ forge: tight });
  G.setForge(forgeState({ secondary_talent_ids: [pickedFirst] }));
  const otherSphere = secondaries.find((id) => sphereOf(id) !== sphereOf(pickedFirst));
  out.complexityGrey = G.secondaryGrey(tight, tight.sources.find((row) => row.id === otherSphere));
  G.setForge(forgeState());
  out.firstSecondaryGrey = G.secondaryGrey(tight, tight.sources.find((row) => row.id === secondaries[0]));
  out.timing60 = (() => { const t0 = Date.now(); for (let i = 0; i < 60; i++) G.secondaryGrey(tight, tight.sources[i % tight.sources.length]); return Date.now() - t0; })();

  // GM override lifts greying.
  gmOn = true;
  G.setForge(forgeState({ secondary_talent_ids: [pickedFirst] }));
  out.gmGrey = G.secondaryGrey(tight, tight.sources.find((row) => row.id === secondaries[0]));
  gmOn = false;

  // Grouping: Sphere headers sorted by name; the hidden note counts what doesn't fit this Base Form.
  G.setData({ forge: fixture.forge });
  G.setForge(forgeState({ base_form: fixture.ward_form }));
  const block = G.forgeBlock();
  const nodes = walk(block, []);
  out.sphereHeads = nodes.filter((n) => (n.props.class || '').includes('grow-sphere-head')).map((n) => text(n));
  out.note = nodes.filter((n) => n.props.id === 'grow-forge-hidden').map((n) => text(n))[0] || '';
  out.gmGroup = nodes.some((n) => text(n) === "Doesn't fit this Base Form (GM)");
  gmOn = true;
  const gmNodes = walk(G.forgeBlock(), []);
  out.gmNote = gmNodes.some((n) => n.props.id === 'grow-forge-hidden' && !n.props.hidden);
  out.gmGroupOn = gmNodes.some((n) => text(n) === "Doesn't fit this Base Form (GM)");

  // Exercise the real onChange -> in-place refresh path: selecting/removing a condition Augment
  // adds/removes its choice dropdown without forcing a whole Forge render.
  const choiceForge = Object.assign({}, fixture.forge, { choices: { major_condition: ['restrained', 'blinded'] },
    augments: [{ augment_id: 'major_condition', complexity: 1, legal: true }] });
  G.setData({ forge: choiceForge });
  G.setForge(forgeState());
  const augmentInput = { checked: true, dataset: { forgePick: 'augment', id: 'major_condition' }, parentElement: { title: '' } };
  domInputs.push(augmentInput);
  G.onChange({ target: augmentInput });
  out.choiceAppears = choiceChildren.some((node) => walk(node, []).some((child) => child.props.dataset?.forgeChoice === 'major_condition'));
  augmentInput.checked = false;
  G.onChange({ target: augmentInput });
  out.choiceDisappears = choiceChildren.length === 0;
  console.log(JSON.stringify(out));
})().catch((error) => { console.error(error && error.stack || String(error)); process.exit(1); });
"""


def _fixture(tmp_path):
    ids = _talent_ids(2000)
    picked = [PRIMARY, AREA, TARGET_MOVE, SELF_MOVE]
    # Two talents from each of several Spheres (not Fire), so swap and new-Sphere cases both exist.
    by_sphere = {}
    for cid in ids:
        sphere = MECHANICS[cid].get("sphere_id")
        if sphere != MECHANICS[PRIMARY].get("sphere_id") and len(by_sphere.setdefault(sphere, [])) < 2:
            by_sphere[sphere].append(cid)
    spread = [cid for pair in list(by_sphere.values())[:4] for cid in pair]
    candidates = sorted(set(picked + spread))
    assert len({MECHANICS[cid].get("sphere_id") for cid in candidates} - {MECHANICS[PRIMARY].get("sphere_id")}) >= 3
    sources = [{"id": cid, "name": MECHANICS[cid].get("display_name") or cid,
                "sphere": MECHANICS[cid].get("sphere_id"), "sphere_id": MECHANICS[cid].get("sphere_id")} for cid in candidates]
    forms = [{"form_id": fid, "display_name": fid.title(), "complexity": 1, "starting_cp": 0, "use": "fixture"}
             for fid in rules()["forms"]]
    fit = fit_table(candidates, MECHANICS, rules())
    forge = {"available": True, "minimum_cl": 5, "known": 0, "limit": 3, "max_complexity": 5, "max_spheres": 2,
             "sphere_complexity": 1, "forms": forms, "sources": sources, "augments": [], "drawbacks": [], "choices": {},
             "fit": fit}
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps({"forge": forge, "primary": PRIMARY, "candidates": candidates, "ward_form": "ward"}))
    return path, fit, candidates


def test_grow_forge_menu_greys_groups_and_hides(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    fixture_path, fit, candidates = _fixture(tmp_path)
    script = tmp_path / "grow_forge.cjs"
    script.write_text(NODE_SCRIPT, encoding="utf-8")
    run = subprocess.run([node, str(script), str(GROW_JS), str(fixture_path)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout.strip().splitlines()[-1])

    assert out["sphereLimitGrey"] and "Spheres" in out["sphereLimitGrey"]
    assert out["swapGrey"] == ""
    assert out["complexityGrey"] and "Complexity" in out["complexityGrey"]
    assert out["firstSecondaryGrey"] == ""
    assert out["timing60"] < 16
    assert out["gmGrey"] == ""
    assert out["sphereHeads"] == sorted(out["sphereHeads"])
    primary_sphere = MECHANICS[PRIMARY].get("sphere_id")
    secondaries_here = [cid for cid in candidates if MECHANICS[cid].get("sphere_id") != primary_sphere]
    ward_hidden = sum(1 for cid in secondaries_here if not fit["ward"][cid][0])
    assert out["note"] == ("1 effect hidden: it doesn't work with a Ward." if ward_hidden == 1
                           else f"{ward_hidden} effects hidden: they don't work with a Ward.")
    assert out["gmNote"] is False and out["gmGroupOn"] is True
    assert out["choiceAppears"] and out["choiceDisappears"]


def test_known_sphere_base_abilities_are_forge_sources_and_other_spheres_are_not():
    disease = "tianxia.sphere.disease"
    poison = "tianxia.sphere.poison"
    disease_ids = base_abilities(disease, MECHANICS)
    poison_ids = base_abilities(poison, MECHANICS)
    assert "DISEASE_BASE_SOW_THE_FEVER_SEED" in disease_ids
    assert "POISON_BASE_DELIVER_THE_DOSE" in poison_ids
    known_spheres = {disease, poison}
    known = {effect_id for sphere_id in known_spheres for effect_id in base_abilities(sphere_id, MECHANICS)}
    assert "DISEASE_BASE_SOW_THE_FEVER_SEED" in known
    assert "POISON_BASE_DELIVER_THE_DOSE" in known
    # Grow sources are derived only from Spheres the character actually knows.
    without_disease = {effect_id for sphere_id in {poison} for effect_id in base_abilities(sphere_id, MECHANICS)}
    assert "DISEASE_BASE_SOW_THE_FEVER_SEED" not in without_disease
    assert "POISON_BASE_DELIVER_THE_DOSE" in without_disease
    assert secondary_fit("strike", "DISEASE_BASE_SOW_THE_FEVER_SEED",
                         "POISON_BASE_DELIVER_THE_DOSE", MECHANICS)[0] is False


def test_creation_time_forging_accepts_authority_bound_base_abilities(tmp_path):
    from character_creation.constructed_arts.forged_technique import _effect_row

    disease = MECHANICS["DISEASE_BASE_SOW_THE_FEVER_SEED"]
    poison = MECHANICS["POISON_BASE_DELIVER_THE_DOSE"]
    source_row = lambda effect: {
        "talent_id": effect["mechanic_id"], "sphere_id": effect["sphere_id"],
        "display_name": effect["name"], "record_hash": effect["source"]["text_sha256"],
        "source": {"source_id": "typed_mechanics_authority", "path": effect["source"]["path"],
                   "source_hash": effect["source"]["text_sha256"]},
        "published_text": json.loads((TYPED_AUTHORITY.parent / "typed_mechanics" / "rules_text.json").read_bytes())[effect["mechanic_id"]],
    }
    request = {"seed": "base-effect-regression", "project_id": "fixture", "cl": 6, "pb": 3,
               "path_id": "tianxia.path.qi_cultivation", "key_ability": "INT",
               "known_spheres": [{"sphere_id": disease["sphere_id"], "display_name": "Disease"},
                                 {"sphere_id": poison["sphere_id"], "display_name": "Poison"}],
               "known_talents": [source_row(disease), source_row(poison)],
               "concept": {"base_form": "strike", "primary_talent_id": disease["mechanic_id"],
                           "secondary_talent_ids": [poison["mechanic_id"]]}}
    technique = construct_forged_technique(load_forging_authority(ROOT), request, generator_version=3, design_policy=None)
    assert technique["primary_sphere_effect"]["talent_id"] == disease["mechanic_id"]
    assert technique["secondary_sphere_effects"][0]["talent_id"] == poison["mechanic_id"]
    assert _effect_row(source_row(disease), {"sphere_id": disease["sphere_id"], "display_name": "Disease"})["talent_id"] == disease["mechanic_id"]


def test_legacy_compilation_stays_unchanged_even_for_hidden_composites():
    primary = "DISEASE_BASE_SOW_THE_FEVER_SEED"
    secondary = "POISON_BASE_DELIVER_THE_DOSE"
    technique = {"name": "Fever Dose", "base_form": {"form_id": "strike", "display_name": "Strike"},
                 "primary_sphere_effect": {"talent_id": primary},
                 "secondary_sphere_effects": [{"talent_id": secondary, "talent_name": "Deliver the Dose"}],
                 "augments": [], "drawbacks": [], "cp_cost": {"final": 0}, "action_type": "action"}
    action = mechanic_for(technique, MECHANICS)
    assert action and action["kind"] == "forged_technique" and action["base_form"] == "strike"
    hit_effects = action["effects"][0]["on_hit"]
    damage = next(row for row in hit_effects if row.get("type") == "damage")
    assert {"necrotic", "poison", "psychic", "acid"} <= set(damage["damage_types"])
    assert any(row.get("mark") == "Contagion Token" for row in hit_effects)
    assert any(row.get("type") == "poison_delivery_save" for row in hit_effects)

    # Existing techniques continue to use stable talent ids.
    saved = dict(technique, primary_sphere_effect={"talent_id": PRIMARY},
                 secondary_sphere_effects=[{"talent_id": "ASH_TAL_ASHEN_BURIAL", "talent_name": MECHANICS["ASH_TAL_ASHEN_BURIAL"]["name"]}])
    assert mechanic_for(saved, MECHANICS) is not None
