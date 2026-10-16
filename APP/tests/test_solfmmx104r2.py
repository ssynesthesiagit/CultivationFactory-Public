"""Service projections must retain every resolved rule on table and sheet surfaces."""
import copy
from pathlib import Path
from types import SimpleNamespace

from combat.action_text import layout_action
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop import engine_button_description
from combat.tabletop_service import TabletopService
from combat.status_text import printed_excerpt
from tests.test_factory_combat_compiler import SHEET


def test_menu_retains_compiled_evidence_and_usage_clocks():
    rows = [
        {"display_name": "Evidence only", "parameters": {"typed": {
            "effects": [{"type": "note", "evidence": "Sneak past a guard without being seen."}]}}},
        {"display_name": "Generate Edict Seal", "parameters": {"typed": {
            "source": "foundation.golden_mandate_seal_v0_2B.generate_edict_seal",
            "once": "owner_turn"}}},
    ]
    menu = {"actions": [{"source_definition_id": str(i)} for i in range(len(rows))]}
    engine = SimpleNamespace(action_catalog={str(i): SimpleNamespace(
        economy="NONE", costs=(), parameters=row["parameters"], model_dump=lambda row=row, **_: row)
                                             for i, row in enumerate(rows)})
    before = copy.deepcopy(rows)
    TabletopService._menu_descriptions(menu, engine)
    assert "Sneak past a guard without being seen." in menu["actions"][0]["hover"]["text"]
    limited = menu["actions"][1]
    assert limited["hover"]["fields"]
    assert "available again at the start of your next turn" in limited["hover"]["text"]
    assert limited["description"] == engine_button_description(rows[1])
    assert rows == before


def test_sheet_projects_buttons_and_library_without_mutating_bundle(tmp_path):
    sheet = copy.deepcopy(SHEET)
    record = "foundation.golden_mandate_seal_v0_2B.generate_edict_seal"
    path_record = "tianxia.path.body_refining.feature.extra_attack"
    sheet["selected_record_sections"] = {"path_subpath": [{"record_id": path_record,
        "display_name": "Extra Attack", "full_description": printed_excerpt(path_record, with_markup=True)}],
        "other": [{"record_id": record,
        "display_name": "Generate Edict Seal", "subsection": "Foundation",
        "full_description": printed_excerpt(record, with_markup=True)}]}
    bundle = compile_character(sheet, actor_id="actor:factory.mmx104r2")
    before = copy.deepcopy(bundle)

    class CompiledTable(TabletopService):
        def _bundle_and_summary(self, project_id):
            return sheet, bundle, {"cultivation_level": 17}

    table = CompiledTable(CombatService(Path(__file__).resolve().parents[1], tmp_path), tmp_path)
    response = table.sheet("00000000-abcdef")
    rows = {r["source_definition_id"]: r for r in bundle["action_catalog"]}
    found = 0
    for button in response["buttons"]:
        row = rows.get((button.get("combat") or {}).get("source_definition_id"))
        if row and button.get("description") == engine_button_description(row):
            found += 1
            assert button["hover"]["text"]
            assert button["hover"]["fields"] or button["description"] in button["hover"]["text"]
    assert found
    entries = []
    for group in response["library"]["groups"]:
        entries.extend(group.get("entries") or [])
        for sphere in group.get("spheres") or []:
            entries.append(sphere)
            entries.extend(sphere.get("entries") or [])
    assert entries
    assert {entry["id"] for entry in entries} >= {record, path_record}
    assert all(entry["text"] for entry in entries)
    for entry in entries:
        if entry.get("text"):
            assert entry["hover"]["text"] == layout_action({"label": entry["name"],
                "parameters": {"description": entry["text"]}})["text"]
    assert bundle == before
