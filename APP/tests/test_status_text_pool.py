"""Owner-pool catalogue and observed status checks."""
import copy
import json
import os
import zipfile
from pathlib import Path
import pytest
from combat.condition_text import all_conditions
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.status_text import describe
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET
from tests.test_prefight import SHEET as MELD_SHEET
from tests.status_text_support import ROOT, _install, _rows, assert_specific_status

POOL = Path(os.environ.get("P6_CHARACTER_POOL", "/var/tmp/auto-audit/astra/lock3-inputs/portable_characters"))


def _pool_sheets():
    paths = sorted(POOL.glob("*/current.zip"))
    if not paths:
        pytest.skip(f"Owner read-only pool unavailable: {POOL}; set P6_CHARACTER_POOL")
    sheets = []
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            sheets.append(json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json")))
    # Compilable sheet fixtures in addition to the owner pool. They exercise
    # baseline combat and the ritual/concentration status path missing in AI picks.
    sheets.extend([copy.deepcopy(SHEET), copy.deepcopy(MELD_SHEET)])
    for path in sorted((ROOT / "tests/fixtures").rglob("*.json")):
        document = json.loads(path.read_text())
        if isinstance(document, dict) and document.get("schema") == SHEET.get("schema") and document.get("identity"):
            sheets.append(document)
    return sheets


def test_pool_compiled_condition_and_mark_effects_have_rules_even_if_ai_does_not_choose_them():
    """Complement observed-state coverage with every declared condition/mark effect."""
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.gate2_runtime_content import AN
    from combat.typed_executor import mark_condition_id

    def effects(value):
        if isinstance(value, dict):
            if value.get("type") in {"condition", "mark"}:
                yield value
            for child in value.values():
                yield from effects(child)
        elif isinstance(value, list):
            for child in value:
                yield from effects(child)

    missing, checked = set(), 0
    for i, sheet in enumerate(_pool_sheets()):
        aid = FACTORY_ACTOR_PREFIX + f"p6-{i}"
        bundle = compile_character(sheet, actor_id=aid)
        engine = Gate4ControllerEngine(ROOT, match_seed=f"P6-DECLARED-{i}", typed_bundles=(bundle,),
            roster_setup={"primary_actor_ids": [aid, AN], "team_by_actor": {aid: "team:a", AN: "team:b"},
                          "starting_positions": {aid: {"x": 2, "y": 2}, AN: {"x": 14, "y": 6}}})
        actor = engine.state.actors[aid]
        actors = {aid: actor.display_name}
        definitions = {key: action.display_name for key, action in engine.action_catalog.items()}
        for action in engine.action_catalog.values():
            if action.owner_id != aid:
                continue
            for effect in effects(action.parameters.get("typed") or {}):
                if effect["type"] == "mark":
                    cid = mark_condition_id(str(effect.get("mark") or "Marked"), aid)
                else:
                    name = str(effect.get("condition") or "")
                    if not name:
                        continue
                    cid = name if name.startswith("condition:") else "condition:typed." + name
                row = {"condition_id": cid, "source_definition_id": action.source_definition_id,
                       "source_actor_id": aid, "expires_on": effect.get("expires_on")}
                text = describe(engine, actor, row, effect.get("data") or {}, actors, definitions,
                                condition_rules=all_conditions(), mark_readings=TabletopService.MARK_READINGS)
                checked += 1
                if not text["rule_text"]:
                    missing.add((cid, action.display_name))
    print(f"P6 declared effect coverage: {checked} condition/mark effects; missing={sorted(missing)}")
    assert checked
    assert not missing


def test_every_status_seen_in_pool_ai_fights_has_a_specific_rule(tmp_path):
    """Compile every pool character; bounded duels sample actual emitted statuses.

    Bound is decisions, not a claim that every possible action/condition is seen.
    Raising P6_AI_STEPS deepens sampling without changing production behaviour.
    Owner inputs remain outside Git; only compact IDs/counts are emitted.
    """
    sheets = _pool_sheets()
    for i, sheet in enumerate(sheets):
        bundle = compile_character(sheet, actor_id=FACTORY_ACTOR_PREFIX + f"p6-{i}")
        assert bundle["actor_template"]
        _install(tmp_path, f"p6-{i}", sheet)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    seen, missing = set(), {}
    limit = int(os.environ.get("P6_AI_STEPS", "16"))
    for i in range(0, len(sheets), 2):
        right = (i + 1) % len(sheets)
        mid = combat.create_factory_match(project_ids=[f"p6-{i}"],
            opponent_actor_ids=[FACTORY_ACTOR_PREFIX + f"p6-{right}"], match_seed=f"P6-POOL-{i}")["match_id"]
        for _ in range(limit + 1):
            rows = _rows(table, combat, mid)
            for row in rows:
                seen.add(row["condition_id"])
                if not row["rule_text"]:
                    missing[row["condition_id"]] = row["source_definition_id"]
                assert_specific_status(row, require_rule=False)
            if _ == limit or combat.get_match(mid)["state"].get("terminal_result"):
                break
            combat.local_step(mid)
        table.delete_match(mid)
        print(f"P6 batch: completed duel {i // 2 + 1}/{(len(sheets) + 1) // 2}; observed IDs={len(seen)}", flush=True)
    print(f"P6 coverage: {len(sheets)} compiled sheets; {len(seen)} observed condition IDs; missing={missing}")
    assert seen
    assert not missing
