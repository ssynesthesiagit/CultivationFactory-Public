"""Regressions for the terminology table and the stable-ID transition."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from app.api import _bounded_owner_scratch_sheet
from catalog.service import CoreCatalogImporter
from catalog_authority.cat3 import compiler
from catalog_authority.sphere_identity import UnknownSphereLabel, resolve_sphere_id
from tools import apply_aspect_terms, build_immortal_art_authority
from tools.aspect_terms import TERMS, aspect_terms


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("old", "new"), [
    ("a Fire Sphere talent", "a Way of Fire talent"),
    ("Prerequisite: Lightning sphere", "Prerequisite: Way of Lightning"),
    ("Fate or Karma Sphere access", "Way of Fate or Way of Karma access"),
    ("Earth, Fire, or Water Spheres", "Way of Earth, Way of Fire, or Way of Water"),
    ("the **Space** Sphere", "the **Way of Space**"),
    ("Sphere of Pressure-Point", "Way of Pressure Points"),
    ("**Legal Spheres:**\n- Fate\n- The Hidden Eye", "**Legal Aspects:**\n- Way of Fate\n- Way of the Hidden Eye"),
    ("**Required Sphere:** Karma, Fate, or an equivalent Secret",
     "**Required Aspect:** Way of Karma, Way of Fate, or an equivalent Secret"),
    ("*Spheres: Daemonic, Harvesting, Darkness*", "*Aspects: Daemon, Harvest, Darkness*"),
    ("(Dual Wielding, CL 6+)", "(Twin Weapons, CL 6+)"),
    ("Dao Aspect and Beast Aspect", "Dao Divinity and Beast Form"),
    ("A Sect-Trial Dao Sphere", "A Sect-Trial Dao Aspect"),
    ("Hybrid-Sphere Refinement", "Hybrid-Aspect Refinement"),
    ("a Sphere", "an Aspect"),
    ("an Equipment Sphere", "a Way of Armaments"),
    ("a 20-foot-radius sphere, dome or sphere, sphere of supernatural darkness, glass sphere",
     "a 20-foot-radius sphere, dome or sphere, sphere of supernatural darkness, glass sphere"),
    ("atmosphere, sphere_id, Tianxia_Sphere_Compendium.md, pack.Sphere.id, 85Spheres",
     "atmosphere, sphere_id, Tianxia_Sphere_Compendium.md, pack.Sphere.id, 85Spheres"),
    ("every aspect of Harvesting", "every aspect of Harvesting"),
    ("Medicine and the Bones Aspect", "Medicine and the Bones Aspect"),
])
def test_aspect_wording_and_idempotence(old, new):
    assert aspect_terms(old) == new
    assert aspect_terms(new) == new


def test_all_legacy_and_new_aspect_names_resolve_to_stored_ids():
    registry = ROOT / "catalog_authority/cat1/data/canonical_spheres.v1.json"
    rows = json.loads(registry.read_text(encoding="utf-8"))["records"]
    assert len({row["canonical_sphere_id"] for row in rows}) == 85
    expected_ids = {row["canonical_sphere_id"] for row in rows}
    seen = set()
    for old, full in TERMS["names"].items():
        sphere_id = resolve_sphere_id(full)
        seen.add(sphere_id)
        short = TERMS["short_lists"].get(old, old)
        for label in (f"Sphere of {old}", old, full, short):
            assert resolve_sphere_id(label) == sphere_id, label
    assert seen == expected_ids
    assert resolve_sphere_id("Equipment") == "tianxia.sphere.equipment"
    with pytest.raises(UnknownSphereLabel, match="Unknown Aspect label: 'Way of Badgers'"):
        resolve_sphere_id("Way of Badgers")


def test_cat3_uses_stored_ids_for_renamed_chapters_and_talents(tmp_path, monkeypatch):
    payload, lines = compiler.read_authority(ROOT)
    legacy_catalog = ROOT / "catalog_authority/cat3/generated/catalog_authority.v1.json"
    legacy = json.loads(legacy_catalog.read_text(encoding="utf-8"))
    renamed = [
        aspect_terms(line)
        if line.startswith("# Sphere of ") or line.startswith("#") and any(
            old in line for old in TERMS["entry_names_that_changed"]
        )
        else line
        for line in lines
    ]
    monkeypatch.setattr(compiler, "read_authority", lambda _: (payload, renamed))
    actual = compiler.build(ROOT, tmp_path)
    for group, key in (("spheres", "canonical_sphere_id"), ("talents", "canonical_talent_id"),
                       ("memberships", "membership_id"), ("sphere_base_ability_authority", "runtime_component_id")):
        assert {row[key] for row in actual[group]} == {row[key] for row in legacy[group]}
    assert any(row["display_name"] == "Way of Armaments" for row in actual["spheres"])
    for talent_id, name in (
        ("TAL_QIWEAVING_TWIN_SPHERE_MODULATION", "Twin-Aspect Modulation"),
        ("tianxia.talent.spirit_companions.hosted_battle_aspect", "Hosted Battle Form"),
    ):
        assert next(row["display_name"] for row in actual["talents"] if row["canonical_talent_id"] == talent_id) == name


@pytest.fixture
def background_records(tmp_path):
    (tmp_path / "FACTORY_MANIFEST.json").write_text("{}")
    source = tmp_path / "09_RULES/Source_Text"
    source.mkdir(parents=True)
    (source / "Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md").write_text(
        "## 1. Quick Hands\n"
    )
    path = source / "Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md"
    names = ["Abandoned Orphan", *[f"Test Background {i}" for i in range(30)]]
    summary, sections = [], []
    for index, name in enumerate(names):
        label, talent = ("Way of Armaments", "Hidden Plates") if index == 0 else ("Way of the Harvest", "Camp Gatherer")
        summary.append(f"| {name} | Dexterity | Survival | {label} |")
        sections.append(
            f"## {name}\n### Background Aspect and Talent\n"
            f"- **{label}.** You gain **{talent}**.\n"
            "### Starting Equipment\n### Origin Insight Options\n- Quick Hands\n### Social Hook\n"
        )
    path.write_text("\n".join([*summary, "", *sections]), encoding="utf-8")
    return {row["record_id"]: row for row in CoreCatalogImporter(tmp_path)._backgrounds()}


def test_background_routes_keep_the_existing_supplement_ids(background_records):
    armaments = "tianxia.background_sphere.equipment"
    plates = "tianxia.background_talent.equipment.hidden_plates"
    orphan = background_records["tianxia.background.abandoned_orphan"]
    assert set(orphan["dependencies"]) == {armaments, plates, "tianxia.origin_insight.quick_hands"}
    assert background_records[plates]["dependencies"] == [armaments]
    assert background_records["tianxia.background_talent.harvesting_and_gathering.camp_gatherer"]["dependencies"] == [
        "tianxia.background_sphere.harvesting_and_gathering"
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node (no browser)")
def test_abandoned_orphan_armaments_shows_as_acquired_in_creator(background_records):
    armaments = background_records["tianxia.background_sphere.equipment"]
    sheet = _bounded_owner_scratch_sheet({
        "owner_character_sheet": {"selected_record_sections": {"sphere": [{
            "record_id": armaments["record_id"],
            "display_name": armaments["display_name"],
        }]}},
    })
    assert sheet["spheres"] == [{"name": "Way of Armaments", "canonical_sphere_id": "tianxia.sphere.equipment"}]
    # Exercise the production card renderer without starting an actual browser.
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const {source, sheet} = JSON.parse(fs.readFileSync(0, "utf8"));
const context = {
  document: {createElement: () => ({dataset: {}, append() {}, setAttribute() {}, innerHTML: ""})},
  guidedRun: {owner_view: {scratch_candidate: {sheet}}},
  planningIsEditable: () => true,
  sphereTalentLogic: {talentIdsForSphere: () => []},
  recordCard: () => ({}),
};
const start = source.indexOf("function sphereBaseAbilities(");
const end = source.indexOf("function renderSphereCatalog(", start);
vm.runInNewContext(source.slice(start, end), context, {filename: "app.js"});
const acquired = context.acquiredSphereIds();
function badge(choice_id, canonical_name) {
  const host = {appendChild(card) { this.card = card; }};
  context.document.createElement = () => ({
    dataset: {}, children: [],
    append(...children) { this.children.push(...children); },
    appendChild(child) { this.append(child); return child; },
    setAttribute() {},
  });
  context.appendSphereBrowseCard(host, {choice_id, canonical_name}, false, acquired, {});
  return host.card.children[0].children[1].textContent;
}
process.stdout.write(JSON.stringify([
  badge("tianxia.sphere.equipment", "Equipment"),
  badge("tianxia.sphere.fire", "Way of Armaments"),
]));
"""
    result = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"source": (ROOT / "static/app.js").read_text(encoding="utf-8"), "sheet": sheet}),
        text=True, capture_output=True, check=True, timeout=30,
    )
    assert json.loads(result.stdout) == ["Acquired", "Available"]


def test_divinity_header_does_not_change_immortal_art_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(build_immortal_art_authority, "SEPARATE_ROOT", tmp_path)
    monkeypatch.setattr(build_immortal_art_authority, "HERE", tmp_path)
    path = tmp_path / "Aspect.md"
    for header in ("Dao Aspect", "Dao Divinity"):
        text = (f"**{header}:** Binding\n**Mandate Cost:** 2\n**CP Modifier:** +1 CP\n"
                "**Function:** Bind a target.\n## Factors\n")
        path.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_name(path.name + ".sha256.txt").write_text(f"{digest}  {path.name}\n")
        row = build_immortal_art_authority._aspect_source({
            "folder": "", "filename": path.name, "sha256": digest, "category": "common",
        })
        assert row["aspect_id"] == "tianxia.dao_aspect.binding"
        assert row["mandate_cost"] == 2 and row["cp_modifier"] == 1


@pytest.mark.parametrize(("source", "old", "new", "decision", "read"), [
    ('stored == "Fire Sphere"', '"Fire Sphere"', '"Way of Fire"', "keep", "compared to stored option"),
    ('''db.execute("SELECT * FROM records WHERE kind='sphere'")''',
     '''"SELECT * FROM records WHERE kind='sphere'"''',
     '''"SELECT * FROM records WHERE kind='Aspect'"''', "keep", "SQL enum"),
    ('names = {"Fire Sphere": record_id}', '"Fire Sphere"', '"Way of Fire"', "keep", "serialized dict key"),
    ('registry = {"Fire Sphere", "Water Sphere"}', '"Fire Sphere"', '"Way of Fire"', "keep", "id membership set"),
    ('pick(ctx, ["Sever Sphere"])', '"Sever Sphere"', '"Sever Aspect"', "keep", "recorded choice id"),
    ('line.startswith("Sphere of Fire")', '"Sphere of Fire"', '"Way of Fire"', "keep", "parser input"),
    ('re.match(r"Equipment Sphere", line)', 'r"Equipment Sphere"', 'r"Way of Armaments"', "keep", "pinned grammar"),
    ('f"{name} sphere." in casefolded_pinned_text', ' sphere.', ' Aspect.', "keep", "pinned route marker"),
    ('pick(ctx, options, labels={key: "Sever Sphere"})', '"Sever Sphere"', '"Sever Aspect"', "change", "choice label"),
    ('raise ValueError("Choose a Sphere.")', '"Choose a Sphere."', '"Choose an Aspect."', "change", "message"),
    ('title = f"{name} Sphere"', ' Sphere', ' Aspect', "change", "display title"),
])
def test_apply_obeys_literal_role_rows(tmp_path, source, old, new, decision, read):
    path = tmp_path / "roles.tsv"
    fields = ["file", "line", "column", "anchor", "old", "new", "decision", "read"]
    path.write_text(
        "\t".join(fields) + "\n"
        + "\t".join(["APP/demo.py", "1", str(source.index(old)), *map(json.dumps, (source, old, new)), decision, read])
        + "\n",
        encoding="utf-8",
    )
    roles = apply_aspect_terms._load_code_roles(path)["APP/demo.py"]
    updated = apply_aspect_terms._python(source, roles)
    assert updated == (source.replace(old, new) if decision == "change" else source)
    assert apply_aspect_terms._python(updated, roles) == updated


def test_apply_renames_transient_key_and_reader_together():
    source = (
        'def headings():\n'
        '    sections = {"Sphere": []}\n'
        '    sections["Sphere"].append("one")\n'
        '    return list(sections)\n'
    )
    old, new = '"Sphere"', '"Aspect"'
    roles = [
        apply_aspect_terms.CodeRole(number, line.index(old), line, old, new, "change", "local title key")
        for number, line in enumerate(source.splitlines(), 1) if old in line
    ]
    assert apply_aspect_terms._python(source, roles) == source.replace(old, new)


def test_apply_does_not_infer_permissions_from_wording_or_position():
    visible = 'message = "Choose a Sphere."'
    old, new = '"Choose a Sphere."', '"Choose an Aspect."'
    roles = [apply_aspect_terms.CodeRole(1, visible.index(old), visible, old, new, "change", "display")]
    source = 'record = {"value": "Choose a Sphere."}\n' + visible + '\n'
    assert apply_aspect_terms._python(source, roles) == source.replace(visible, visible.replace(old, new))


def test_apply_keeps_whole_files_pinned_in_tracked_app_sources(tmp_path, monkeypatch):
    from tools import typed_mechanics_helpers as typed

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    pinned, twin = (tmp_path / "APP" / name for name in ("pinned.py", "twin.py"))
    pinned.parent.mkdir()
    old, new = '"Choose a Sphere."', '"Choose an Aspect."'
    anchor = f"message = {old}"
    pinned.write_bytes((anchor + "\n").encode())
    twin.write_bytes((anchor + "\n# These are different file bytes.\n").encode())
    originals = {file: file.read_bytes() for file in (pinned, twin)}

    manifest = tmp_path / "APP/authority/packages/demo/manifest.py"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(f'SOURCE_SHA256 = "{hashlib.sha256(originals[pinned]).hexdigest()}"\n')
    twin_digest = hashlib.sha256(originals[twin]).hexdigest()
    doc = tmp_path / "docs/pins.txt"
    doc.parent.mkdir()
    doc.write_text(twin_digest + "\n")
    subprocess.run(["git", "add", "APP", "docs"], cwd=tmp_path, check=True)
    (tmp_path / "APP/untracked.json").write_text(json.dumps({"sha256": twin_digest}))

    roles = tmp_path / "roles.tsv"
    roles.write_text(
        "file\tline\tcolumn\tanchor\told\tnew\tdecision\tread\n"
        + "".join(
            "\t".join([f"APP/{file.name}", "1", str(anchor.index(old)), *map(json.dumps, (anchor, old, new)),
                       "change", "display"]) + "\n"
            for file in (pinned, twin)
        )
    )
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("")
    reviews, owner_edits = (tmp_path / "APP" / name for name in ("reviews.json", "owner_text_edits.json"))
    for file in (reviews, owner_edits):
        file.write_text("{}")
    monkeypatch.setattr(typed, "REVIEWED_FINAL", reviews)
    monkeypatch.setattr(typed, "OWNER_TEXT_EDITS", owner_edits)
    monkeypatch.setattr(apply_aspect_terms, "_source_rows", lambda raw=False: {})
    monkeypatch.setattr(apply_aspect_terms, "_CODE_ROLES", roles)

    result = apply_aspect_terms.apply(tmp_path, pairs, write=True)

    assert pinned.read_bytes() == originals[pinned]
    assert twin.read_bytes() == originals[twin].replace(old.encode(), new.encode())
    assert result["kept_as_history"] == {"APP/pinned.py": [manifest.relative_to(tmp_path).as_posix()]}
