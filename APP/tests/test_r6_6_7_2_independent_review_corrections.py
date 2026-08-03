from __future__ import annotations

import re
from pathlib import Path

from combat.history_feed import format_history_feed

ROOT = Path(__file__).resolve().parents[1]


def _function_body(script: str, name: str, next_name: str) -> str:
    return script.split(f"function {name}", 1)[1].split(f"function {next_name}", 1)[0]


def test_history_transition_stops_auto_and_preserves_selected_boundary() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    history = script.split("async function setCombatHistoryIndex", 1)[1].split("async function returnCombatLive", 1)[0]
    step = script.split("async function runOneLocalStep", 1)[1].split("function runTrackedCombatAutoStep", 1)[0]
    run = script.split('document.getElementById("combatLocalRun").onclick', 1)[1].split('document.getElementById("combatLocalStop")', 1)[0]

    assert "combatAutoRunning = false" in history
    assert "combatExecutionEpoch += 1" in history
    assert "combatHistoryTransitionPending = true" in history
    assert "const pendingStep = combatAutoStepPromise" in history
    assert "if (pendingStep) await pendingStep" in history
    assert "presentation?boundary=${combatHistoryIndex}" in history
    assert "historySelectedDuringStep" in step
    assert "!historySelectedDuringStep" in step
    assert "!combatIsHistorical()" in run
    assert "executionEpoch === combatExecutionEpoch" in run
    assert "Return to Live" not in history


def test_pinned_actor_disables_turn_follow_and_keeps_one_identity() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "if (combatPinnedActorId)" in script
    assert "combatFollowCurrentTurn = false;" in script
    assert "combatSelectedActorId = combatPinnedActorId" in script
    pin = re.search(r'combatSheetButton\("Pin", \(\) => \{([^}]*)\}\)', script)
    assert pin, "Pin handler must be explicit"
    body = pin.group(1)
    assert "combatPinnedActorId = actor.entity_id" in body
    assert "combatSelectedActorId = actor.entity_id" in body
    assert "combatFollowCurrentTurn = false" in body


def test_character_sheet_claim_is_honest_and_raw_authority_is_advanced_only() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    character_section = script.split("function combatSheetCharacterSection", 1)[1].split("function combatFeedItemInvolvesActor", 1)[0]
    footer = script.split('const actions = document.createElement("footer")', 1)[1].split("host.appendChild(actions)", 1)[0]

    assert "does not expose a navigable full persistent Character Sheet" in character_section
    assert "Combat entity" not in character_section
    assert "Match revision" not in character_section
    assert "combatHasPersistentCharacterSheet(actor)" in footer
    assert 'id="combatCharacterAuthorityDetails"' in html
    assert "CHARACTER AUTHORITY DETAILS" in html
    assert "This is not the full persistent Character Sheet" in script


def test_phone_tokens_have_44px_targets_and_accessible_dynamic_state() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/styles.css").read_text(encoding="utf-8")
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")

    assert "current turn" in script
    assert "selected for inspection" in script
    assert 'token.setAttribute("aria-pressed"' in script
    assert 'id="combatHistoryStatus" role="status" aria-live="polite" aria-atomic="true"' in html
    assert "min-width: max(100%, calc(var(--board-columns) * 54px))" in css
    assert "min-width: 44px; min-height: 44px" in css
    assert ".combat-token.companion-token { width: min(82%, calc(100% - 6px)); }" in css


def test_actor_history_uses_exact_ids_and_system_events_are_explicit() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    helper = script.split("function combatFeedItemInvolvesActor", 1)[1].split("function combatSheetHistorySection", 1)[0]
    section = script.split("function combatSheetHistorySection", 1)[1].split("function renderCombatSheetInto", 1)[0]

    assert "item.actor_id === actorId" in helper
    assert "targets.includes(actorId)" in helper
    assert 'item.identity_scope === "SYSTEM"' in helper
    assert "combatFeedItemInvolvesActor(item, actor.entity_id)" in section
    assert "actor.display_name" not in section

    rows = format_history_feed(
        [
            {"sequence": 1, "event_type": "HOLD_POSITION_COMMITTED", "actor_id": "actor:b", "target_ids": [], "payload": {}},
            {"sequence": 2, "event_type": "ROUND_STARTED", "actor_id": None, "target_ids": [], "payload": {"round": 2}},
            {"sequence": 3, "event_type": "DAMAGE_APPLIED", "actor_id": "actor:b", "target_ids": ["actor:a"], "payload": {"amount": 3}},
        ],
        [],
        pre_state=None,
        post_state={"actors": {}, "round_number": 2},
        actor_names={"actor:a": "Twin", "actor:b": "Twin"},
        definition_names={},
    )
    assert rows[0]["actor_id"] == "actor:b" and rows[0]["identity_scope"] == "ACTOR_TARGET"
    assert rows[1]["identity_scope"] == "SYSTEM"
    assert rows[2]["target_ids"] == ["actor:a"] and rows[2]["identity_scope"] == "ACTOR_TARGET"


def test_non_fourteen_row_grid_is_typed_and_presentation_only() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/styles.css").read_text(encoding="utf-8")
    board = script.split("function renderCombatBoard", 1)[1].split("function combatSheetButton", 1)[0]
    assert 'host.style.setProperty("--board-rows", battlefield.height_squares)' in board
    assert "calc(100% / var(--board-rows))" in css
    assert "calc(100% / 14)" not in css
    assert "actor.position =" not in board
