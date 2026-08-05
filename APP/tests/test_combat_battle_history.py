from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from combat.gate2_runtime_models import ActionIntent
from combat.gate2_scripted import _matches, load_script
from combat.gate3_scripted import execute_persistent_script
from combat.gate3_storage import Gate3Persistence
from combat.gate5_service import CombatService
from combat.history_feed import format_history_feed

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "combat_gate2/scripted/Gate2_Scripted_Fight_Input.json"


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != ".writer.lock"
    }


def _exact_intent(session, step_index: int) -> ActionIntent:
    step = load_script(SCRIPT_PATH).steps[step_index - 1]
    matches = [candidate for candidate in session.engine.legal_candidates() if _matches(candidate, step)]
    assert len(matches) == 1
    candidate = matches[0]
    return ActionIntent(
        intent_id=f"intent:history-test:{step_index:04d}",
        decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,
        state_version=candidate.state_version,
        actor_id=candidate.actor_id,
        target_ids=candidate.target_ids,
        destination=candidate.destination,
        option_ids=step.option_ids,
        reaction_decisions=step.reaction_decisions,
    )


def test_visual_manifest_declares_public_safe_fallback_without_uncertain_artwork() -> None:
    root = ROOT / "static/combat_visuals"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "TianxiaFactoryBattleVisualAssets.v1"
    assert manifest["default_map_asset_id"] is None
    assert manifest["maps"] == []
    assert manifest["tokens"] == []
    assert manifest["artwork_policy"]["status"] == "EXCLUDED_PENDING_POSITIVE_PROVENANCE"
    assert set(manifest["artwork_policy"]["excluded_legacy_paths"]) == {
        "heavenly_arena_r1.png", "an_eui_r1.png", "lee_jia_r1.png", "ling_qi_r1.png", "bai_meizhen_r1.png"
    }
    assert manifest["fallback"]["kind"] == "INITIALS"
    assert "Cui" in manifest["fallback"]["note"]
    assert not list(root.glob("*.png"))
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "stable_actor_ids || []).includes(actorId)" in script
    assert "fallback:initials" in script
    assert "display_name.toLowerCase" not in script


def test_read_only_history_uses_ordered_commit_reducer_boundaries(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = persistence.create_match(match_seed="TIANXIA-GATE2-MANUAL-0001", maximum_rounds=20)
    session.execute_intent(_exact_intent(session, 1))
    session.execute_intent(_exact_intent(session, 2))
    before = _tree_hashes(session.store.match_dir)
    history = persistence.history_boundaries(session.match_id)
    after = _tree_hashes(session.store.match_dir)
    replay = session.replay()

    assert before == after
    assert history["read_only"] is True
    assert history["commit_count"] == 2
    assert len(history["boundaries"]) == 3
    assert [row["boundary_kind"] for row in history["boundaries"]] == ["GENESIS", "COMMIT", "COMMIT"]
    assert [row["record_sequence"] for row in history["boundaries"]] == [0, 2, 4]
    assert history["canonical_final_state_sha256"] == replay["canonical_state_sha256"]
    assert history["canonical_event_log_sha256"] == replay["canonical_event_log_sha256"]
    assert history["canonical_roll_log_sha256"] == replay["canonical_roll_log_sha256"]
    assert history["boundaries"][-1]["state"] == replay["state"]


def test_movement_history_reports_reducer_before_and_after_coordinates(tmp_path: Path) -> None:
    session, _ = execute_persistent_script(ROOT, tmp_path / "UserData", SCRIPT_PATH)
    history = session.persistence.history_boundaries(session.match_id)
    movement_index = next(
        index for index, boundary in enumerate(history["boundaries"])
        if any(event["event_type"] == "MOVEMENT_COMMITTED" for event in boundary["events"])
    )
    boundary = history["boundaries"][movement_index]
    movement = next(event for event in boundary["events"] if event["event_type"] == "MOVEMENT_COMMITTED")
    actor_id = movement["actor_id"]
    before = history["boundaries"][movement_index - 1]["state"]["actors"][actor_id]["position"]
    after = boundary["state"]["actors"][actor_id]["position"]
    assert before != after
    assert after == movement["payload"]["destination"]


def test_history_service_formats_recorded_rolls_and_preserves_legacy_metadata_absence(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    persistence = Gate3Persistence(ROOT, userdata)
    session = persistence.create_match(match_seed="TIANXIA-GATE2-MANUAL-0001", maximum_rounds=20)
    for step_index in range(1, 8):
        session.execute_intent(_exact_intent(session, step_index))
    service = CombatService(ROOT, userdata)
    metadata_path = session.store.match_dir / "FactoryIntegration.json"
    assert not metadata_path.exists()
    before = _tree_hashes(session.store.match_dir)
    view = service.history(session.match_id)
    after = _tree_hashes(session.store.match_dir)

    assert before == after
    assert not metadata_path.exists()
    assert view["read_only"] is True
    assert view["metadata"]["read_only_default"] is True
    assert view["boundaries"][-1]["state"]["actors"]
    feed = [item for boundary in view["boundaries"] for item in boundary["feed"]]
    attack = next(item for item in feed if item["event_type"] == "ATTACK_ROLLED")
    save = next(item for item in feed if item["event_type"] == "SAVE_ROLLED")
    damage_roll = next(item for item in feed if item["event_type"] == "DAMAGE_ROLLED")
    damage = next(item for item in feed if item["event_type"] == "DAMAGE_COMMITTED")
    assert "AC " in attack["summary"] and "total " in attack["summary"]
    assert attack["summary"].endswith(("— Hit.", "— Miss."))
    assert "DC " in save["summary"] and "total " in save["summary"]
    assert "damage against" in damage_roll["summary"] and "total " in damage_roll["summary"]
    assert "HP remained" in damage["summary"]

    fallback = format_history_feed(
        [{
            "sequence": 999,
            "event_type": "OLDER_UNDETAILED_EVENT",
            "source_definition_id": "legacy:unknown",
            "trigger_or_intent_id": "legacy",
            "transaction_id": "legacy",
            "actor_id": None,
            "target_ids": [],
            "payload": {},
        }],
        [],
        pre_state=None,
        post_state={"actors": {}},
        actor_names={},
        definition_names={},
    )[0]
    assert fallback["detailed_breakdown_recorded"] is False
    assert fallback["summary"] == "Detailed breakdown was not recorded for this event."


def test_history_ui_is_scrubbable_read_only_and_responsive() -> None:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/styles.css").read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    assert {
        "combatHistoryPanel", "combatHistorySlider", "combatHistoryPrevious", "combatHistoryNext",
        "combatHistoryJump", "combatReturnLive", "combatHistoricalBanner", "combatHistoryRaw",
        "combatDecisionPanel", "combatControllerPanel", "combatAIBridgePanel",
    }.issubset(ids)
    assert 'type="range"' in html
    assert "combatIsHistorical()" in script
    assert 'document.getElementById(panelId).hidden = historical' in script
    assert 'Historical view is read-only. Return to Live before submitting an action.' in script
    assert '/history`' in script
    assert "ArrowLeft" in script and "ArrowRight" in script
    assert "grid-template-columns: repeat(var(--board-columns), minmax(0, 1fr))" in css
    assert "min-width: 620px" not in css
    assert "overflow-x: clip" in css


def test_windows_packaging_declares_visual_assets_and_history_tests() -> None:
    spec = (ROOT / "packaging/windows_portable/TianxiaFactory.spec").read_text(encoding="utf-8")
    selfcheck = (ROOT / "packaging/windows_portable/windows_build_selfcheck.py").read_text(encoding="utf-8")
    build = (ROOT / "packaging/windows_portable/Build-WindowsPortable.ps1").read_text(encoding="utf-8")
    assert '(str(ROOT / "static"), "static")' in spec
    assert "static/combat_visuals/manifest.json" in selfcheck
    assert "test_combat_battle_history.py" in build
