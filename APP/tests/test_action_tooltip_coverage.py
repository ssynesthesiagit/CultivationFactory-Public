"""Action hover text stays readable across the portable roster and table menu."""
import json
import zipfile
from collections import Counter

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop import auto_buttons
from combat.tabletop_service import TabletopService
from tests.test_status_text import POOL, ROOT, _install


def test_every_portable_action_has_hover_text_and_domain_armament_manifest_resolves_in_menu(tmp_path):
    paths = sorted(POOL.glob("*/current.zip"))
    if not paths:
        pytest.skip(f"Owner read-only pool unavailable: {POOL}; set P6_CHARACTER_POOL")

    domain_project = None
    checked = 0
    table_states = 0
    missing_menu_text = []
    row_counts = Counter()
    table_menu_rows = 0
    manual_menus = 0
    other_menus = 0
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    for index, path in enumerate(paths):
        with zipfile.ZipFile(path) as archive:
            sheet = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))
        project = path.parent.name
        bundle = compile_character(sheet, actor_id=FACTORY_ACTOR_PREFIX + project)
        rows = [row for row in auto_buttons(bundle, bundle.get("summary") or {}) if row.get("group") != "checks"]
        for row in rows:
            row_counts[row.get("group", "unknown")] += 1
            text = str(row.get("description") or "").strip()
            if not text or text.casefold() == str(row.get("label") or "").strip().casefold():
                missing_menu_text.append((row.get("label"), row.get("combat", {}).get("source_definition_id")))
            checked += 1
        for row in bundle.get("prefight", {}).get("options") or []:
            row_counts["prefight"] += 1
            text = str(row.get("description") or row.get("text") or "").strip()
            if not text or text.casefold() == str(row.get("name") or "").strip().casefold():
                missing_menu_text.append((row.get("name"), row.get("action_id")))
            checked += 1
        has_domain_manifest = any(row.get("label") == "Domain Armament: Manifest" for row in rows)
        _install(tmp_path, project, sheet)
        actor_id = FACTORY_ACTOR_PREFIX + project
        match_id = combat.create_factory_match(project_ids=[project], control_modes={actor_id: "MANUAL"},
                                               match_seed=f"L73-POOL-{index}")["match_id"]
        state = table.state(match_id)
        assert state.get("schema") and state.get("menu")
        table_states += 1
        # Audit the menu rows this character actually gets, manual or not, so no
        # row is silently skipped: count both kinds and report the split.
        menu = state["menu"]
        if menu.get("manual"):
            manual_menus += 1
        else:
            other_menus += 1
        for row in menu.get("actions") or []:
            table_menu_rows += 1
            text = str(row.get("description") or "").strip()
            if not text or text.casefold() == str(row.get("label") or "").strip().casefold():
                missing_menu_text.append((row.get("label"), row.get("source_definition_id")))
        table.delete_match(match_id)
        if has_domain_manifest:
            domain_project = project

    assert checked > 0
    assert table_states == len(paths)
    assert not missing_menu_text, sorted(set(missing_menu_text))[:40]
    print({"characters": len(paths), "table_states": table_states,
           "compiled_rows_by_group": dict(row_counts), "table_menu_rows": table_menu_rows,
           "manual_menus": manual_menus, "non_manual_menus": other_menus,
           "empty_or_name_only_after": len(missing_menu_text)})
    if domain_project is None:
        pytest.skip("No portable character in the read-only pool has Domain Armament: Manifest")
    actor_id = FACTORY_ACTOR_PREFIX + domain_project
    match_id = combat.create_factory_match(project_ids=[domain_project], control_modes={actor_id: "MANUAL"},
                                           match_seed="LUNA73-MENU-AUDIT")["match_id"]
    menu = table.state(match_id)["menu"]
    if not (menu.get("manual") and menu.get("actor_id") == actor_id):
        combat.set_controller_mode(match_id, actor_id=actor_id, controller_mode="MANUAL")
        menu = table.state(match_id)["menu"]
    row = next(row for row in menu["actions"] if row.get("label") == "Domain Armament: Manifest")
    assert row["description"] and "Manifest" in row["description"]
