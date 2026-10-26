"""Regression checks for the GROW4 review fixes: one ASI per level, GM confirmation kept per Path, no duplicate pickers,
and a pending add's Subpath rows present in every planned level."""
import shutil
import subprocess
from pathlib import Path

import pytest

from combat import table_levelup as lu
from stage2.ability_changes import published_path_records
from tests.test_grow3_levelup import BODY, PID, QI, TALENTS, service
from tests.test_grow4a_multipath import _add_payload, _reach

ROOT = Path(__file__).resolve().parents[1]


def _sheet(paths, granted):
    return {"identity": {"path_ids": list(paths), "paths": [{"path_id": p, "effective_cl": 1} for p in paths]},
            "path_and_subpath": {"path_record_ids": list(paths), "path_feature_record_ids": list(granted)}}


def _asi_rows(rows):
    return [r for r in rows if r["canonical_id"].endswith("ability_score_improvement_or_cultivation_insight")]


def test_catch_up_grants_one_shared_asi_when_second_path_is_added():
    records = published_path_records()
    body_asi = _stage2_asi(records[BODY])
    qi_asi = _stage2_asi(records[QI])
    assert body_asi["shared_rule_id"] == qi_asi["shared_rule_id"]
    # Qi is added at CL5 to a character who already holds Body Refining (CL1 features granted, ASI from CL4 granted).
    held = [body_asi["canonical_id"]]
    sheet = _sheet([BODY], held)
    sheet["identity"]["cultivation_level"] = 4
    notes = []
    rows = lu._feature_rows(sheet, 5, {}, QI, notes)
    assert not _asi_rows(rows)
    assert notes


def test_catch_up_keeps_asi_when_no_shared_grant_is_held():
    sheet = _sheet([BODY], [])
    rows = lu._feature_rows(sheet, 5, {}, QI, [])
    assert len(_asi_rows(rows)) == 1


def _stage2_asi(record):
    rows = lu._stage2(record)["features"]
    return next(r for r in rows if r["canonical_id"].endswith("ability_score_improvement_or_cultivation_insight"))


def test_gm_override_on_path_is_not_satisfied_by_subpath_confirmation():
    choices = {"add_path_id": QI, "add_access": "gm", "add_source_id": "GM", "access_confirmed": True}
    add = lu._choice_add(choices)
    assert not add["confirmed"]
    problem = lu._add_problem(_sheet([BODY], []), add, 3)
    assert problem


def test_gm_override_passes_only_with_its_own_confirmation():
    choices = {"add_path_id": QI, "add_access": "gm", "add_source_id": "GM", "add_confirmed": True}
    add = lu._choice_add(choices)
    assert add["confirmed"]
    assert not lu._add_problem(_sheet([BODY], []), add, 3)


def test_pending_add_subpath_rows_reach_later_planned_levels(tmp_path):
    # Regression: subpath_progressions covered only held Paths, so a Subpath from a pending add had no CL6 rows.
    s = service(tmp_path, BODY)
    _reach(s, 5)
    view = s.advancement(PID)["level_up"]
    sub = next(r for g in view["add_templates"][QI]["subpaths"] for r in g["options"] if not r["requires_confirmation"])
    expected = {f["granted_at_cl"] for f in lu.source().subpaths[sub["id"]]["feature_progression"]}
    progression = {p["cl"] for p in view["subpath_progressions"][sub["id"]]}
    assert 6 in expected and progression == expected


def test_two_levels_in_one_batch_with_add_at_first_level_commit_together(tmp_path):
    s = service(tmp_path, BODY)
    _reach(s, 5)
    first = _add_payload(s.advancement(PID), QI)
    second = {"cl": 6, "talent_ids": [TALENTS[4]["canonical_talent_id"]], "subpaths": {}, "feature_choices": {}}
    s.level_up(PID, {**first, "levels": [first, second]})
    cold = s.combat._factory_owner_sheet(PID)
    assert cold["identity"]["cultivation_level"] == 6
    assert cold["identity"]["path_levels"] == {BODY: 6, QI: 6}
    assert cold["path_and_subpath"]["path_progression_entries_by_cl"]["6"] == [BODY, QI]
    granted = cold["path_and_subpath"]["path_feature_record_ids"]
    sub = first["subpaths"][QI]
    later = [f["canonical_id"] for f in lu.source().subpaths[sub]["feature_progression"] if f["granted_at_cl"] == 6]
    assert later and all(f in granted for f in later)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for the DOM-free level plan check")
def test_level_plan_has_no_duplicate_feature_or_subpath_rows():
    source = (ROOT / "static/tabletop/grow.js").read_text().replace("export ", "")
    script = source + r"""
const assert = require("node:assert/strict");
deps = {h: (tag, props, ...children) => ({tag, props, children}), $: () => null};
// The held Path's group and feature appear in both the menu and the add template (the template lists every held row).
// The pending Path's group and feature appear only in the template, so they must be supplied exactly once.
const feat = {feature_id: "f.pick", prompt: "Pick", options: [{id: "a", name: "A"}]};
const shared = {feature_id: "f.shared", prompt: "Shared", options: [{id: "b", name: "B"}]};
const bodyGroup = {path_id: "p.body", name: "Body", options: [{id: "s0", name: "S0", legal: true}]};
const qiGroup = {path_id: "p.qi", name: "Qi", options: [{id: "s1", name: "S1", legal: true}]};
data = {cl: 3, level_up: {cl: 3, available: true, add_templates: {"p.qi": {subpaths: [bodyGroup, qiGroup], feature_choices: [shared, feat]}}, planning: [
  {cl: 3, talent_count: 1, talents: [], statistics: {}, subpaths: [bodyGroup], feature_choices: [shared]}],
  statistics: {pb: 2, hp: {maximum: 10}}, talents: []}};
levelDraft = {target: 3, rows: {}, filters: {}, addPath: {path_id: "p.qi"}};
const plan = levelPlan();
const m = plan[0].menu;
assert.equal(m.subpaths.filter((g) => g.path_id === "p.qi").length, 1);
assert.equal(m.subpaths.filter((g) => g.path_id === "p.body").length, 1);
assert.equal(m.feature_choices.filter((r) => r.feature_id === "f.pick").length, 1);
assert.equal(m.feature_choices.filter((r) => r.feature_id === "f.shared").length, 1);
assert.equal(plan[0].build.filter((r) => r.feature_id === "f.pick").length, 1);
assert.equal(plan[0].build.filter((r) => r.feature_id === "f.shared").length, 1);
"""
    subprocess.run([shutil.which("node"), "-e", script], check=True, text=True, capture_output=True)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for the DOM-free level plan check")
def test_level_add_path_shows_the_recorded_method_without_a_typed_id():
    # Regression (GROW4F3R): a Primary Method grant asked for a free-text "Source name" and only accepted the
    # character's internal Method id, which the panel never showed. The panel now names the recorded Method and
    # sends its id automatically, so no id field exists for that access source.
    source = (ROOT / "static/tabletop/grow.js").read_text().replace("export ", "")
    script = source + r"""
const assert = require("node:assert/strict");
deps = {h: (tag, props, ...children) => ({tag, props: props || {}, children}), $: () => null};
const method = {id: "METHOD-002", name: "Ash-Breath Furnace Method"};
data = {level_up: {primary_method: method}};
levelDraft = {target: null, rows: {}, filters: {}, addPath: {path_id: "p.qi", access: "primary_method", source_id: "", confirmed: false}};
const block = addPathBlock({add_candidates: [], add_templates: {}, primary_method: method, duplicate_notes: []});
const flat = (n) => Array.isArray(n) ? n.flatMap(flat) : (n && typeof n === "object" ? [n, ...(n.children || []).flatMap(flat)] : []);
const nodes = flat(block);
assert.equal(nodes.filter((n) => n.props && n.props.dataset && n.props.dataset.levelAddPath === "source_id").length, 0);
assert.deepEqual(nodes.filter((n) => n.tag === "strong").map((n) => n.children.join("")), [method.name]);
onChange({target: {id: "level-add-access", value: "primary_method", dataset: {levelAddPath: "access"}}});
assert.equal(levelDraft.addPath.source_id, "METHOD-002");
// A different access source asks for its own name, so the Method id is not carried over.
onChange({target: {id: "level-add-access", value: "phb", dataset: {levelAddPath: "access"}}});
assert.equal(levelDraft.addPath.source_id, "");
"""
    subprocess.run([shutil.which("node"), "-e", script], check=True, text=True, capture_output=True)
