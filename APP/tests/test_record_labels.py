"""Public synthetic regressions for ID relationships and presentation-only names."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import Database, Settings
from catalog.service import CatalogService
from character_sheet.path_display import path_display
from combat import factory_compiler, senses, stealth, zones
from combat.fighter_picker import card_fields
from combat.tabletop import sheet_summary
from factory_authoring.record_links import bind_records
from non_sphere_authority.owner_subpaths import load_owner_subpaths, owner_feature_sources, published_owner_section
from non_sphere_authority.service import NonSphereAuthorityService
from record_labels import presentation_diff
from tests import hunt36_support as table_support
from tests.lighting_darkness_support import darkness_rules

APP = Path(__file__).resolve().parents[1]
SUBPATH = "tianxia.subpath.qi.cai_clan_empyreal_administrator"
QI = "tianxia.path.qi_cultivation"
DARK = "DARK_BASE_DARKNESS"
TAMER = "TAL_BEASTMASTERY_BEAST_TAMER"


def _write_labels(app, names):
    path = app / "authority/record_labels.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(names))


def _owner_app(app):
    features = [{"canonical_id": SUBPATH + f".feature.synthetic_{cl}", "display_name": f"Feature {cl}",
                 "granted_at_cl": cl, "source_markdown": f"### Feature {cl}\nCost: {cl} Qi\nSynthetic rules."}
                for cl in (3, 6, 10, 14, 18)]
    record = {"canonical_id": SUBPATH, "display_name": "Original school", "owning_path_id": QI,
              "catalog_order": 81, "prerequisites": {"minimum_cl": 3}, "access": {},
              "feature_progression": features}
    path = app / "non_sphere_authority/authority/owner_subpaths.d/synthetic.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": "Tianxia.OwnerSubpaths.v1", "pack_id": "tianxia.owner.subpaths.synthetic",
                               "pack_version": "1.0.0", "entries": [record]}))
    return record


def test_one_parent_label_drives_catalog_selection_sheet_and_table_without_mechanical_pack_change(tmp_path, monkeypatch):
    app = tmp_path / "app"
    record = _owner_app(app)
    _write_labels(app, {SUBPATH: "Original school"})
    before_sources = owner_feature_sources(app)
    before_rows, before_commitments = load_owner_subpaths(app, presentation=False)

    # Capture the real pack builder's inputs. This still exercises normalization,
    # source inventory and feature commitments; installation itself is covered by
    # the unchanged owner-Subpath service tests.
    db = Database(Settings.from_env(APP, tmp_path / "data"))
    db.migrate()
    db.settings = replace(db.settings, root_dir=app)
    catalog = CatalogService(db)
    captures = []
    monkeypatch.setattr(catalog, "_rebuild_builtin_supplement",
                        lambda *args, **kwargs: captures.append((deepcopy(args), kwargs)))
    catalog._rebuild_owner_subpaths(SimpleNamespace(owner_root=app), tmp_path / "factory")

    with db.transaction() as conn:
        conn.execute("INSERT INTO content_packs(pack_id,version,pack_hash,lifecycle_state,authority,installed_path,manifest_json,installed_at) "
                     "VALUES(?,?,?,?,?,?,?,?)", ("synthetic", "1", "a"*64, "published", "canonical", str(tmp_path), "{}", "now"))
        conn.execute("INSERT INTO catalog_records(record_id,content_type,display_name,pack_id,pack_version,authority,publication_state,"
                     "source_path,source_anchor,source_hash,record_hash,data_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (SUBPATH, "subpath", "Original school", "synthetic", "1", "canonical", "published",
                      "synthetic.json", SUBPATH, "b"*64, "c"*64, "{}"))
        catalog._rebuild_fts(conn)

    # One edit, no owner document/rules or ext code edits and no pack-version bump.
    _write_labels(app, {SUBPATH: "Temporary renamed school"})
    monkeypatch.setattr("record_labels.APP", app)
    rows, commitments = load_owner_subpaths(app)
    assert rows[0]["display_name"] == "Temporary renamed school"
    assert owner_feature_sources(app) == before_sources
    assert load_owner_subpaths(app, presentation=False) == (before_rows, before_commitments)
    assert commitments == before_commitments
    catalog._rebuild_owner_subpaths(SimpleNamespace(owner_root=app), tmp_path / "factory")
    assert captures[0] == captures[1]
    assert catalog.search(content_type="subpath")["records"][0]["display_name"] == "Temporary renamed school"
    assert catalog.search(q="Temporary", content_type="subpath")["records"][0]["record_id"] == SUBPATH
    assert catalog.legal_choices(content_type="subpath")[0]["display_name"] == "Temporary renamed school"

    # The selection surface uses the same validated source rows as admission.
    authority = object.__new__(NonSphereAuthorityService)
    authority.root, authority.subpaths = app, {SUBPATH: record}
    assert authority.subpath_catalog(QI)["records"][0]["display_name"] == "Temporary renamed school"
    sheet = {"path_and_subpath": {"paths": [{"path_id": QI, "display_name": "Qi Cultivation"}],
                                  "subpaths": [{"subpath_id": SUBPATH, "owning_path_id": QI,
                                                "display_name": "Stale saved label"}],
                                  "subpath": {"subpath_id": SUBPATH, "owning_path_id": QI, "name": "Stale saved label"}},
             "ability_scores_and_statistics": table_support.sheet([])["ability_scores_and_statistics"]}
    expected = [{"path": "Qi Cultivation", "subpaths": ["Temporary renamed school"]}]
    assert path_display(sheet)["path_entries"] == expected
    assert card_fields(sheet)["path_entries"] == expected
    assert card_fields(sheet)["subpath"] == "Temporary renamed school"
    assert sheet_summary(sheet)["path_entries"] == expected
    for source in before_sources:
        assert published_owner_section(app, source["source"]) == source["text"]
        bad = {**source["source"], "source_file_sha256": "0"*64}
        assert published_owner_section(app, bad) == ""
    diff = presentation_diff({SUBPATH: "Original school"}, {SUBPATH: "Temporary renamed school"})
    assert diff["aspect"] == "presentation" and diff["before_sha256"] != diff["after_sha256"]
    assert diff["changes"] == {SUBPATH: {"before": "Original school", "after": "Temporary renamed school"}}


def _mechanic(rid, name, economy="passive", effects=(), modifier=None):
    return {"mechanic_id": rid, "name": name, "sphere_id": "tianxia.sphere.water", "kind": "talent",
            "activation": {"economy": economy}, "effects": list(effects), "riders": [],
            "range": {"kind": "feet", "feet": 30}, "area": None, "duration": {"kind": "instant"},
            "cost": [], **({"modifier": modifier} if modifier else {})}


def _synthetic_sheet(ids):
    """Own synthetic rows directly; the on-disk authority cannot classify them."""
    sheet = table_support.sheet([], cl=10)
    sheet["spheres_and_talents"] = {"learned_talent_record_ids": list(ids)}
    return sheet


def _modifiers():
    hit = [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
            "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["force"]}]}]
    return {"PULSE": _mechanic("PULSE", "Pulse", "action", hit),
            "OTHER": _mechanic("OTHER", "Other", "action", hit),
            "BOOST": _mechanic("BOOST", "Boost", modifier={"targets": ["Pulse"], "scope": "named", "when": "hit",
                     "optional": True, "limit": "none", "extra_cp": 1,
                     "effects": [{"type": "extra_damage", "flat": 2, "damage_types": ["force"]}]})}


def test_binding_then_renaming_or_duplicating_visible_names_cannot_retarget_modifiers():
    raw = _modifiers()
    linked = bind_records(raw)
    sheet = _synthetic_sheet(raw)
    old = factory_compiler.compile_character(sheet, actor_id=table_support.LEFT, typed_authority={"mechanics": raw})
    admitted = factory_compiler.compile_character(sheet, actor_id=table_support.LEFT, typed_authority={"mechanics": linked})
    assert old == admitted  # every field, including all actions/payments/variants and diagnostics
    renamed = deepcopy(linked)
    renamed["PULSE"]["name"] = "New Pulse"
    renamed["OTHER"]["name"] = "Pulse"
    bundle = factory_compiler.compile_character(sheet, actor_id=table_support.LEFT, typed_authority={"mechanics": renamed})
    assert {row["display_name"] for row in bundle["action_catalog"]} >= {"New Pulse", "New Pulse + Boost", "Pulse"}
    assert "Pulse + Boost" not in {row["display_name"] for row in bundle["action_catalog"]}
    expected = deepcopy(admitted)
    for action in expected["action_catalog"]:
        if action["display_name"] in ("Pulse", "Pulse + Boost"):
            action["display_name"] = action["display_name"].replace("Pulse", "New Pulse", 1)
        elif action["display_name"] == "Other":
            action["display_name"] = "Pulse"
    for report in expected["modifiers"]:
        report["targets"] = ["New Pulse" if name == "Pulse" else name for name in report["targets"]]
        report["applied"] = ["New Pulse" if name == "Pulse" else name for name in report["applied"]]
        report["variants"] = ["New Pulse + Boost" if name == "Pulse + Boost" else name for name in report["variants"]]
    # Recompute, rather than suppress, the authenticity commitment after the
    # exact declared label changes. Every remaining field must still match.
    from combat.canonical import canonical_sha256
    expected.pop("bundle_sha256")
    expected["bundle_sha256"] = canonical_sha256(expected)
    assert bundle == expected


def test_presentation_projection_follows_exact_input_review_without_weakening_fingerprints():
    from factory_authoring.record_links import project_authority
    from factory_authoring.rider_pattern_overlay import SCHEMA, apply, digest
    original = _mechanic("ROW", "Source heading", effects=[{"type": "damage", "flat": 1, "damage_types": ["force"]}])
    original.update(source={"text_sha256": "a" * 64}, riders=["Original rider"], coverage="CORE_WITH_RIDERS")
    converted = {**original, "riders": [], "coverage": "FULL"}
    receipt = {"schema": SCHEMA, "mechanics": {"ROW": {
        "text_sha256": "a" * 64, "input_sha256": digest(original), "output_sha256": digest(converted),
        "set": {"riders": []}, "remove": []}}}
    source = {"mechanics": {"ROW": deepcopy(original)}}
    assert apply(source, receipt) == {"ROW": "applied"}
    assert source == {"mechanics": {"ROW": converted}}
    projected = project_authority(source, {}, {"ROW": "Current label"})
    assert source == {"mechanics": {"ROW": converted}}, "projection must not rewrite the source"
    assert projected["mechanics"]["ROW"]["name"] == "Current label"
    assert projected["mechanics"]["ROW"]["source"] == original["source"]
    assert projected["mechanics"]["ROW"]["riders"] == []
    # Applying a source receipt to altered input must still reject it: there is
    # no ignore-name/ignore-hash path to make unrelated input look authentic.
    assert apply(projected, receipt) == {"ROW": "changed_typing"}


def test_short_modifier_reference_keeps_its_choose_one_option_id_after_parent_rename():
    records = _modifiers()
    records["PULSE"]["name"] = "Basin"
    records["PULSE"]["options"] = [
        {"label": "Mist", "effects": deepcopy(records["PULSE"]["effects"])},
        {"label": "Water", "effects": deepcopy(records["PULSE"]["effects"])}]
    records["PULSE"]["effects"] = []
    records["BOOST"]["modifier"]["targets"] = ["Mist Basin"]
    linked = bind_records(records)
    assert linked["BOOST"]["modifier"]["target_links"] == [
        {"ids": [], "fallback_ids": ["PULSE#opt0"]}]
    linked["PULSE"]["name"] = "Renamed basin"
    bundle = factory_compiler.compile_character(_synthetic_sheet(records),
        actor_id=table_support.LEFT, typed_authority={"mechanics": linked})
    names = {a["display_name"] for a in bundle["action_catalog"]}
    assert "Renamed basin: Mist + Boost" in names
    assert "Renamed basin: Water + Boost" not in names


def test_named_reaction_modifier_reaches_every_compiled_trigger_row_by_source_id():
    records = {"REPLY": _mechanic("REPLY", "Reply", "reaction"),
               "RIDER": _mechanic("RIDER", "Rider", modifier={
                   "targets": ["Reply"], "scope": "named", "when": "success",
                   "effects": [{"type": "condition", "condition": "reaction_denied"}]})}
    records = bind_records(records)
    reactions = {key: {"feature_id": "REPLY", "name": "Renamed reply", "effects": [],
                       "reaction_modes": [{"index": 0, "effects": []}, {"index": 1, "effects": []}]}
                 for key in ("REPLY", "REPLY#1")}
    _report, consumed = factory_compiler._attach_reaction_modifiers(
        reactions, list(records), records, set())
    assert consumed == {"RIDER"}
    assert all(row["effects"][-1]["condition"] == "reaction_denied" for row in reactions.values())
    assert all(mode["effects"][-1]["condition"] == "reaction_denied"
               for row in reactions.values() for mode in row["reaction_modes"])


def test_area_family_membership_and_pairing_do_not_follow_display_names(darkness_rules):
    before = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    owned = [DARK, "TAL_DARK_NUMBING_DARKNESS", "TAL_DARK_PURE_DARKNESS", "TAL_DARK_PITCH_BLACK"]
    sheet = table_support.sheet(owned, cl=10)
    base = factory_compiler.compile_character(sheet, actor_id=table_support.LEFT, typed_authority=before)
    after = deepcopy(before)
    for rid in owned:
        after["mechanics"][rid]["name"] = "Same visible name"
    changed = factory_compiler.compile_character(sheet, actor_id=table_support.LEFT, typed_authority=after)
    def shape_contracts(bundle):
        return {a["source_definition_id"]: (a["parameters"]["shape_talents"], a["parameters"]["shape_costs"],
                                           a["parameters"]["shape_default"])
                for a in bundle["action_catalog"] if a["parameters"].get("zone_shape")}
    assert shape_contracts(changed) == shape_contracts(base)
    assert any(len(talents) == 2 for talents, _costs, _default in shape_contracts(changed).values())


def test_tamer_eligibility_is_owned_source_id_not_visible_name():
    records = {TAMER: _mechanic(TAMER, "Renamed handler"),
               "IMPOSTOR": _mechanic("IMPOSTOR", "Beast Tamer")}
    def compile_owned(ids):
        return factory_compiler.compile_character(_synthetic_sheet(ids), actor_id=table_support.LEFT,
                                                   typed_authority={"mechanics": records})
    assert compile_owned([TAMER])["summons"]
    assert not compile_owned(["IMPOSTOR"])["summons"]
    assert compile_owned([TAMER])["summon_options"]["tamer"] is True
    assert compile_owned(["IMPOSTOR"])["summon_options"]["tamer"] is False
    missing_source = factory_compiler.compile_character(_synthetic_sheet([TAMER]),
        actor_id=table_support.LEFT, typed_authority={"mechanics": {"IMPOSTOR": records["IMPOSTOR"]}})
    assert not missing_source["summons"]


def test_renamed_darkness_keeps_perception_and_hide_identity_through_table_commit_reload(tmp_path, monkeypatch, darkness_rules):
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    authority["mechanics"][DARK]["name"] = "Evening Veil"
    original = table_support.compile_character
    def renamed(*args, **kwargs):
        bundle = original(*args, typed_authority=authority, **kwargs)
        bundle.setdefault("senses", {}).setdefault("rows", []).append(
            {"feature_id": "test:vision", "sense": "darkvision", "range_ft": 60, "when": "always"})
        if bundle["actor_id"] == table_support.LEFT:
            bundle["senses"]["meld_start"] = "TAL_DARK_HIDE_IN_DARKNESS"
        return bundle
    monkeypatch.setattr(table_support, "compile_character", renamed)
    combat, table, mid = table_support.fight(tmp_path, [DARK, "TAL_DARK_HIDE_IN_DARKNESS"])
    table_support.turn(combat, table, mid)
    engine = table_support.reload(combat, mid)
    hide = next(a for a in engine.action_catalog.values() if a.parameters.get("stealth") == "hide")
    assert hide.parameters["hide_inside"] == "Evening Veil"
    assert hide.parameters["hide_area_id"] == DARK
    candidate = next(c for c in engine.legal_candidates()
                     if c.destination is not None and (c.destination.x, c.destination.y) == (3, 6)
                     and engine.action_catalog[c.source_definition_id].display_name == "Evening Veil")
    table_support.send(combat, table, mid, candidate.candidate_id)
    engine = table_support.reload(combat, mid)
    zone = next(z for z in zones.typed_zones(engine) if z.owner_id == table_support.LEFT)
    me, foe = engine.state.actors[table_support.LEFT], engine.state.actors[table_support.RIGHT]
    assert zone.trigger_profile["name"] == "Evening Veil"
    assert zone.trigger_profile["source_profile"]["mechanic_id"] == DARK
    assert stealth.in_own_area(engine, me, DARK)
    assert senses.pierces(engine, zone, me, foe)
    # A duplicate visible name is not the original area and grants neither rule.
    zone.trigger_profile["source_profile"]["mechanic_id"] = "SYNTHETIC_OTHER_AREA"
    assert not stealth.in_own_area(engine, me, DARK)
    assert not senses.pierces(engine, zone, me, foe)


def test_pure_darkness_rule_keys_on_mechanic_id_not_its_printed_label(monkeypatch):
    # Renaming the shaping talent's label must not change the printed sense rule: the zone carries the sealed ID.
    from combat import zones
    monkeypatch.setattr(zones, "shaping_of", lambda actor, family: ["TAL_DARK_PURE_DARKNESS"])
    row = {"name": "Renamed Pure Darkness", "obscured": "heavy", "inside_text": ["Darkvision is reduced to 5 feet."]}
    shaped, need = zones.shaped_spec(None, SimpleNamespace(resources={}),
                                     {"family": "Darkness", "shapes": {"TAL_DARK_PURE_DARKNESS": row}})
    assert shaped["talents"] == ["Renamed Pure Darkness"]
    assert shaped["talent_ids"] == ["TAL_DARK_PURE_DARKNESS"]
    assert senses._pure(SimpleNamespace(trigger_profile={"talents": shaped["talents"], "talent_ids": shaped["talent_ids"]}))
    assert not senses._pure(SimpleNamespace(trigger_profile={"talents": ["Unrelated renamed label"]})), "arbitrary labels confer nothing"
    rule = senses.rules()["pure"]
    assert rule["source_id"] == "TAL_DARK_PURE_DARKNESS" and "talent" not in rule


def test_dark_plug_in_talent_membership_uses_ids_not_zone_labels():
    from combat.zone_identity import has_talent
    zone = SimpleNamespace(trigger_profile={"talents": ["Renamed Slick"],
                                            "talent_ids": ["TAL_DARK_SHADOW_SLICK"]})
    assert has_talent(zone, "TAL_DARK_SHADOW_SLICK")
    zone.trigger_profile["talent_ids"] = ["TAL_DARK_FEARFUL_DARKNESS"]
    zone.trigger_profile["talents"] = ["Shadow Slick"]
    assert not has_talent(zone, "TAL_DARK_SHADOW_SLICK")
    zone.trigger_profile["talent_ids"] = []
    assert not has_talent(zone, "TAL_DARK_SHADOW_SLICK"), "an explicit empty ID list is authoritative"


def test_legacy_darkness_profile_name_still_grants_darkvision_through_rule(monkeypatch):
    from factory_authoring import printed_references
    # Public exports omit printed prose; this is the same immutable-heading contract.
    monkeypatch.setattr(printed_references, "source_headings", lambda: ({DARK: "### Darkness"}, {"Darkness": [DARK]}))
    zone = SimpleNamespace(trigger_profile={"name": "Darkness", "visual": {"darkness": True}})
    monkeypatch.setattr(senses, "perception_senses", lambda *_args, **_kwargs: {"darkvision": {"range_ft": 60}})
    monkeypatch.setattr(senses, "reach", lambda *_args, **_kwargs: 60)
    monkeypatch.setattr(senses, "_within", lambda *_args, **_kwargs: True)
    assert senses.pierces(None, zone, None, None)
    zone.trigger_profile["name"] = "An unrelated renamed label"
    assert not senses.pierces(None, zone, None, None)


def test_catalog_search_indexes_current_labels_before_filters_and_pagination(tmp_path):
    app = tmp_path / "app"
    db = Database(Settings.from_env(APP, tmp_path / "data"))
    db.migrate()
    db.settings = replace(db.settings, root_dir=app)
    catalog = CatalogService(db)
    with db.transaction() as conn:
        conn.execute("INSERT INTO content_packs(pack_id,version,pack_hash,lifecycle_state,authority,installed_path,manifest_json,installed_at) "
                     "VALUES(?,?,?,?,?,?,?,?)", ("synthetic", "1", "a"*64, "published", "canonical", str(tmp_path), "{}", "now"))
        for rid, kind in (("first", "subpath"), ("second", "subpath"), ("excluded", "talent")):
            conn.execute("INSERT INTO catalog_records(record_id,content_type,display_name,pack_id,pack_version,authority,publication_state,"
                         "source_path,source_anchor,source_hash,record_hash,data_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                         (rid, kind, "Source " + rid, "synthetic", "1", "canonical", "published",
                          "synthetic.json", rid, "b"*64, "c"*64, '{"summary":"martial training"}'))
        catalog._rebuild_fts(conn)
        stored = [tuple(row) for row in conn.execute("SELECT * FROM catalog_records ORDER BY row_id")]
    _write_labels(app, {"first": "Temporary school", "second": "Temporary temple", "excluded": "Temporary talent"})
    # Both query terms must match one record's indexed label + existing content.
    pages = [catalog.search(q="Temporary martial", content_type="subpath", limit=1, offset=i)["records"]
             for i in (0, 1, 2)]
    assert all(len(page) == 1 for page in pages[:2]) and pages[2] == []
    assert {row["record_id"] for page in pages for row in page} == {"first", "second"}
    assert {row["display_name"] for page in pages for row in page} == {"Temporary school", "Temporary temple"}
    assert catalog.search(q="Source first")["records"][0]["record_id"] == "first"
    # No pack rebuild or timestamp tick is required for a second edit or removal.
    _write_labels(app, {"first": "Current school"})
    assert catalog.search(q="Current")["records"][0]["record_id"] == "first"
    assert catalog.search(q="Temporary")["records"] == []
    assert catalog.search(q="Source second")["records"][0]["display_name"] == "Source second"
    with db.connection() as conn:
        assert [tuple(row) for row in conn.execute("SELECT * FROM catalog_records ORDER BY row_id")] == stored


def test_catalog_get_applies_labels_without_changing_the_stored_record(tmp_path):
    import shutil
    from catalog.service import _normalize_record
    from contracts.canonical import normalize_core_catalog_record

    app = tmp_path / "app"
    shutil.copytree(APP / "schemas", app / "schemas")
    _write_labels(app, {"parent": "New parent"})
    db = Database(Settings.from_env(APP, tmp_path / "data"))
    db.migrate()
    db.settings = replace(db.settings, root_dir=app)
    projection = _normalize_record(record_id="parent", content_type="talent", display_name="Old parent",
                                   source_path="synthetic.json", source_hash="b" * 64, raw={},
                                   pack_id="synthetic", pack_version="1")
    record = normalize_core_catalog_record(projection, pack_hash="a" * 64)
    stored = json.dumps(record)
    with db.transaction() as conn:
        conn.execute("INSERT INTO content_packs(pack_id,version,pack_hash,lifecycle_state,authority,installed_path,manifest_json,installed_at) "
                     "VALUES(?,?,?,?,?,?,?,?)", ("synthetic", "1", "a"*64, "published", "canonical", str(tmp_path), "{}", "now"))
        conn.execute("INSERT INTO catalog_records(record_id,content_type,display_name,pack_id,pack_version,authority,publication_state,"
                     "source_path,source_anchor,source_hash,record_hash,data_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("parent", "talent", "Old parent", "synthetic", "1", "canonical", "published",
                      "synthetic.json", "parent", "b"*64, record["record_hash"], stored))
    catalog = CatalogService(db)
    assert catalog.search()["records"][0]["display_name"] == "New parent"
    result = catalog.get("parent")
    assert result["display_name"] == "New parent"
    assert result["source"] == record["source"]
    assert result["record_hash"] == record["record_hash"]
    variants = catalog.get("parent", include_all_versions=True)
    assert variants["selected"] == variants["variants"][0] == result
    with db.connection() as conn:
        assert conn.execute("SELECT data_json FROM catalog_records").fetchone()["data_json"] == stored


def test_subpath_catalog_labels_each_nested_feature_without_mutating_source(tmp_path):
    record = _owner_app(tmp_path)
    source = deepcopy(record)
    names = {SUBPATH: "New parent", **{row["canonical_id"]: f"Renamed feature {row['granted_at_cl']}"
                                     for row in record["feature_progression"]}}
    _write_labels(tmp_path, names)
    authority = object.__new__(NonSphereAuthorityService)
    authority.root, authority.subpaths = tmp_path, {SUBPATH: record}
    result = authority.subpath_catalog(QI)["records"][0]
    assert result["display_name"] == "New parent"
    assert [row["display_name"] for row in result["feature_progression"]] == [
        names[row["canonical_id"]] for row in source["feature_progression"]]
    assert record == source
    for before, after in zip(source["feature_progression"], result["feature_progression"]):
        assert after == {**before, "display_name": names[before["canonical_id"]]}


def test_label_table_is_parsed_once_until_its_bytes_change(tmp_path, monkeypatch):
    import record_labels
    _write_labels(tmp_path, {DARK: "Darkness"})
    calls, real = [], json.loads
    monkeypatch.setattr(record_labels.json, "loads", lambda s, *a, **k: (calls.append(1), real(s, *a, **k))[1])
    for _ in range(3):
        assert record_labels.labels(tmp_path)[DARK] == "Darkness"
    assert len(calls) == 1, "the ~4,950-entry table must not be re-parsed on every call"
    _write_labels(tmp_path, {DARK: "Shadow"})
    assert record_labels.labels(tmp_path)[DARK] == "Shadow", "an edit is seen at once"


def test_compiler_and_record_links_share_one_normalizer(monkeypatch):
    from combat import factory_compiler
    from factory_authoring import record_links
    monkeypatch.setattr(record_links, "normalized", lambda value: "SHARED")
    assert factory_compiler._norm_name("Pure Darkness") == "SHARED"


def test_ambiguous_printed_heading_is_rejected_without_console_output(monkeypatch, capsys):
    from combat import stealth
    from factory_authoring import printed_references
    monkeypatch.setattr(printed_references, "source_headings", lambda: ({}, {"Darkness": ["a", "b"]}))
    assert stealth.in_own_area(SimpleNamespace(), SimpleNamespace(entity_id="x"), "Darkness") is False
    output = capsys.readouterr()
    assert output.err == output.out == ""
