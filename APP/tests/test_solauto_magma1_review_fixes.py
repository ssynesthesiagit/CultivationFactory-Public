"""Regression tests for the Sol SOLAUTO-MAGMA1 review findings.

Each test fails on the pre-fix branch:
- Furnace Mantle lost its printed save Advantage and scent Disadvantage rows (review finding 1);
- stale GM-run reminders appeared in the active player-facing card for turn-start riders that now resolve natively;
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


def _player_text():
    return json.loads((TYPED / "player_text.json").read_text())


def _text(obj):
    return json.dumps(obj, ensure_ascii=False)


@pytest.mark.parametrize("record", sorted(STALE_REMINDERS))
def test_stale_gm_run_reminder_is_not_projected_to_players(record):
    # Evidence maps are retained for audit; only the actual projected card is player-facing.
    active_player_text = _player_text()["records"][record]
    assert STALE_REMINDERS[record] not in active_player_text


@pytest.mark.parametrize("reminder", FURNACE_STALE_HEAT_PRESSURE)
def test_furnace_mantle_heat_pressure_reminders_are_not_projected(reminder):
    # Keep audit evidence intact, while ensuring it is not projected into the player card.
    active_player_text = _player_text()["records"]["TAL_MAGMA_FURNACE_MANTLE"]
    assert reminder not in active_player_text


def test_rebuilt_runtime_authority_contains_reviewed_magma_effects():
    runtime = json.loads((APP / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]

    def effects(record):
        found = []
        def walk(value):
            if isinstance(value, dict):
                if value.get("type") in {"magma_heat_pressure", "rider_damage_state"}:
                    found.append(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(runtime[record])
        return found

    assert any(row.get("own_molten_immunity") and row.get("magma_check_hazards") for row in effects("TAL_MAGMA_MAGMA_ARMOR"))
    assert any("magma_save_tags" in row for row in effects("TAL_MAGMA_OBSIDIAN_SKIN"))
    assert any(row.get("near_hostile_turn_start") for row in effects("TAL_MAGMA_FURNACE_MANTLE"))
    for record in ("TAL_MAGMA_HEAVEN_FALLING_METEOR", "TAL_MAGMA_VOLCANIC_SMOKE"):
        assert any(row["type"] == "magma_heat_pressure" for row in effects(record))


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
