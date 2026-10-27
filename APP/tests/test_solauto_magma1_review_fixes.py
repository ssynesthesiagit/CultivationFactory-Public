"""Regression tests for the Sol SOLAUTO-MAGMA1 review findings.

Each test fails on the pre-fix branch:
- Furnace Mantle lost its printed save Advantage and scent Disadvantage rows (review finding 1);
- stale GM-run reminders stayed in owner_text_edits.json evidence maps for turn-start riders that now resolve natively;
- skill_check published its d20 scope only for actual tools, so a pending next-check condition could not consume its roll.
"""
import json
from pathlib import Path

import pytest

from combat.typed_executor import Context
from test_auto_lane1 import ME, AN, _engine
from test_riders_lane14 import bundle

APP = Path(__file__).resolve().parents[1]
TYPED = APP / "authority" / "typed_mechanics"
STALE_REMINDERS = {
    "TAL_MAGMA_OBSIDIAN_SKIN": "GM-run: turn-start damage and downstream damage riders; the locked engine suppresses nested damage events.",
    "TAL_MAGMA_FURNACE_MANTLE": "GM-run: turn-start Fire damage and downstream damage riders; the locked engine suppresses nested damage events.",
    "TAL_MAGMA_MAGMA_ARMOR": "Immunity to damage from your own Molten Terrain remains GM-run; hit damage executes. Grappler turn-start damage and downstream damage riders are GM-run until locked nested-event delivery is available.",
}
FURNACE_STALE_HEAT_PRESSURE = (
    "Heat Pressure choice: disadvantage on the next Strength or Dexterity check (GM-run one-check consumption).",
    "Heat Pressure: the creature must choose willing movement or an Action on its next turn, not both (GM-run economy gate).",
)


def _owner_edits():
    return json.loads((TYPED / "owner_text_edits.json").read_text())["records"]


def _player_text():
    return json.loads((TYPED / "player_text.json").read_text())


def _text(obj):
    return json.dumps(obj, ensure_ascii=False)


@pytest.mark.parametrize("record", sorted(STALE_REMINDERS))
def test_stale_gm_run_reminder_is_not_projected_to_players(record):
    # The reminder described turn-start riders the engine now resolves natively (grappler damage asserted by
    # test_riders_lane1). Its raw key no longer exists in typing, so the owner map must not keep it.
    edits = _owner_edits()[record]
    assert STALE_REMINDERS[record] not in _text(edits.get("player_evidence") or {})
    assert STALE_REMINDERS[record] not in _text(_player_text()["evidence"])


@pytest.mark.parametrize("reminder", FURNACE_STALE_HEAT_PRESSURE)
def test_furnace_mantle_heat_pressure_reminders_are_not_projected(reminder):
    # Heat Pressure's check consumption and economy gate are native now (magma_heat_pressure).
    assert reminder not in _text(_owner_edits()["TAL_MAGMA_FURNACE_MANTLE"].get("player_evidence") or {})
    assert reminder not in _text(_player_text()["evidence"])


def test_obsidian_skin_player_text_has_no_by_hand_damage_reminder():
    text = json.dumps(_player_text()["records"]["TAL_MAGMA_OBSIDIAN_SKIN"], ensure_ascii=False)
    assert "by hand" not in text


def test_furnace_mantle_keeps_its_printed_save_and_scent_defences():
    rows = json.loads((TYPED / "reviewed_final.d" / "elements.json").read_text())["mechanics"]["TAL_MAGMA_FURNACE_MANTLE"]["effects"]
    save = [e for e in rows if e["type"] == "advantage" and e.get("on", "").startswith("saving throws against ordinary smoke")]
    scent = [e for e in rows if e["type"] == "disadvantage" and e.get("on") == "checks relying on scent"]
    assert len(save) == 1 and save[0]["applies_to"] == "self"
    assert len(scent) == 1 and scent[0]["applies_to"] == "enemies_in_area" and scent[0]["distance_ft"] == 5
    armor = next(e for e in rows if e["type"] == "rider_damage_state")
    assert "magma_save_tags" not in armor and "scent_radius_ft" not in armor


def test_skill_check_with_a_pending_condition_still_publishes_its_ability(monkeypatch):
    from combat.ext.tabik_dark import skill_check

    e = _engine(bundle())
    me = e.state.actors[ME]
    e._apply_condition(me, "condition:typed.check_mode", "test:pending", ME,
                       expires_on="UNTIL_REMOVED", data={"rule": {"check_mode": {"ALL": "ADVANTAGE"}}})
    scopes = []
    real = e.d20_scope

    def record(ctx):
        scopes.append(ctx)
        return real(ctx)

    monkeypatch.setattr(e, "d20_scope", record)
    action = next(iter(e.action_catalog.values()))
    skill_check(Context(e, e.state.actors[AN], action, None, {"numbers": {"save_dc": 50}}, [me], me),
                {"type": "skill_check", "ability": "DEX", "skill": "Acrobatics"})
    checks = [s for s in scopes if s.get("kind") == "check"]
    assert len(checks) == 1 and checks[0]["ability"] == "DEX"
