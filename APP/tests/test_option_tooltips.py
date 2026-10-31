"""SOL155: the real sheet and persisted table menu carry printed option rules."""
import json
from pathlib import Path
import subprocess
import pytest

from combat.gate5_service import CombatService
from combat.factory_compiler import compile_character
from combat.tabletop_service import TabletopService
from combat.option_text import CHOICE_LINE
from combat.status_text import printed_rules
from tests.option_tooltip_support import OWNER, sheet, rows
from tests.test_status_text import _install

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def synthetic_printed_options(tmp_path, monkeypatch):
    """Test projection with stable synthetic prose, not public-export redactions.

    Real compiler, sheet, table, persistence and Node builders remain in use.
    Only their printed reference input is synthetic; no mechanics are replaced.
    """
    from combat import status_text, option_text
    rules = {**status_text.printed_rules(),
        "printed_option:Breath-Checking Strike": (
            "##### Open the Gate\nWhen you Open a creature, choose an effect.\n"
            "###### Breath-Checking Strike\nThe target cannot take Opportunity Attacks until the start of its next turn."),
        "printed_option:Centerline Impact": (
            "###### Centerline Impact\nWhen the triggering attack deals damage, add your Proficiency Bonus to that damage."),
        "printed_option:Hooking Step": (
            "###### Hooking Step\nMove yourself 5 feet without provoking Opportunity Attacks."),
        "printed_option:Numbing Darkness": (
            "###### Numbing Darkness\nApply Numbing Darkness to the selected area."),
        "printed_option:Persistent Darkness": (
            "###### Persistent Darkness\nThe selected area lasts without Concentration."),
        "printed_option:unmaking.overdraw": (
            "###### Overdraw\nOn the next qualifying hit, add bonus Ruin damage."),
        "TAL_VOID_NULLIFYING_STRIKE": (
            "#### Nullifying Strike\nCost: 2 cultivation points or 2 Stamina\n"
            "The target makes a Constitution saving throw.\nFailed Save: Choose one:\n"
            "the target becomes Hollowed until the start of your next turn;\n"
            "the target cannot take Reactions until the start of its next turn;\n"
            "suppress one ordinary temporary Resistance until the start of your next turn;\n"
            "reduce the target’s Speed by 10 feet until the start of your next turn.\n"
            "Successful Save: The target cannot gain Temporary HP until the start of your next turn."),
        "foundation.ancient_desolate_sacred_body_v0_2C.saint_body_rebuke": (
            "#### Saint-Body Rebuke\nCost: 1 Golden Sea Pulse\n"
            "After a qualifying hit, choose one rider: "
            "push the target 5 feet if it is no more than one size larger than you; "
            "the target cannot take Reactions against you until the start of your next turn; or "
            "you gain Advantage on the next eligible Saint-Body Frame resistance roll "
            "against that target before the start of your next turn."),
    }
    from factory_authoring import record_display
    from factory_authoring.player_rules import build_player_text
    data = tmp_path / "display"
    data.mkdir()
    edits = {}
    for name, value in {"rules_text.json": rules, "owner_text_edits.json": {"records": edits},
                        "record_sections.json": {}, "player_text.json": build_player_text(rules, edits)}.items():
        (data / name).write_text(json.dumps(value))
    monkeypatch.setattr(record_display, "DATA", data)
    monkeypatch.setattr(record_display, "SECTIONS", data / "record_sections.json")
    path = tmp_path / "synthetic-option-rules.json"
    path.write_text(json.dumps(rules))
    monkeypatch.setattr(status_text, "RULES_TEXT_PATH", path)
    option_text._names.cache_clear()
    yield
    option_text._names.cache_clear()






def test_node_sheet_builder_rejects_explicitly_empty_real_rows(tmp_path):
    rows_file = tmp_path / "sol155-rows.json"
    rows_file.write_text("[]")
    result = subprocess.run(
        ["node", "tests/option_tooltips.test.mjs", str(rows_file)], cwd=ROOT,
        text=True, capture_output=True)
    assert result.returncode != 0
    assert "Real row missing" in result.stdout + result.stderr


