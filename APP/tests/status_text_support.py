"""Shared helpers for the status-text tests: a synthetic sheet installed as a portable package, the table
fixture and the condition-row reader.  Nothing here reads the owner's character pool."""
import json
import zipfile
from pathlib import Path
from combat.canonical import canonical_sha256
from combat.condition_text import all_conditions
from combat.gate5_service import CombatService
from combat.status_text import describe
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET


ROOT = Path(__file__).resolve().parents[1]


def _install(root, project, sheet):
    folder = root / "portable_characters" / project
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))


def _rows(table, combat, mid):
    engine = combat._load_session(mid).engine
    before = canonical_sha256(engine.state.model_dump(mode="json"))
    events = canonical_sha256([e.model_dump(mode="json") for e in engine.events])
    state = table.state(mid)
    assert canonical_sha256(engine.state.model_dump(mode="json")) == before
    assert canonical_sha256([e.model_dump(mode="json") for e in engine.events]) == events
    rows = [row for actor in state["presentation"]["actors"] for row in actor["conditions"]]
    # Conditions can be created and consumed inside one AI decision. The event
    # source still allows ID coverage even when its transient instance is gone.
    actors, definitions = table._names_for(mid, engine)
    rules = all_conditions()
    for event in engine.events:
        if event.event_type != "CONDITION_APPLIED":
            continue
        event_row = {"condition_id": event.payload["condition_id"], "source_definition_id": event.source_definition_id,
                     "source_actor_id": event.actor_id, "expires_on": event.payload.get("expires_on")}
        event_row.update(describe(engine, engine.state.actors.get(event.target_ids[0]), event_row, {}, actors, definitions,
                                 condition_rules=rules, mark_readings=table.MARK_READINGS))
        rows.append(event_row)
    return rows


def _tooltip_table(tmp_path, monkeypatch):
    _install(tmp_path, "left", SHEET)
    combat = CombatService(ROOT, tmp_path)
    mid = combat.create_factory_match(project_ids=["left"], match_seed="P6-WORDING")["match_id"]
    session = combat._load_session(mid)
    table = TabletopService(combat, tmp_path)
    # Project a real engine instance through the service; injected saved statuses
    # let the test cover old fights whose original action is no longer available.
    monkeypatch.setattr(table, "_load_state_session", lambda match_id: session)
    return table, mid, session.engine


def assert_specific_status(row, *, require_rule=True):
    if require_rule:
        assert row["rule_text"]
    assert "No automatic effect; see its source" not in row["detail"]
    assert row["duration"] and row["applied_by"] and row["source_ability"]
