"""SOL155: the real sheet and persisted table menu carry printed option rules."""
import json
import re
import subprocess
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.option_tooltip_support import OWNER, PROJECT, ROOT, option_match


@pytest.fixture(autouse=True)
def synthetic_printed_options(tmp_path, monkeypatch):
    """Test projection with stable synthetic prose, not public-export redactions.

    Real compiler, sheet, table, persistence and Node builders remain in use.
    Only their printed reference input is synthetic; no mechanics are replaced.
    """
    from combat import status_text, option_text
    rules = {**status_text.printed_rules(),
        "TAL_DARK_NUMBING_DARKNESS": (
            "### Numbing Darkness - Darkness\n"
            "Synthetic Darkness shape used by this option-listing fixture."),
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

GATE = ["open_the_gate.breath", "open_the_gate.centerline", "open_the_gate.hooking"]
OVERDRAW = ["overdraw.off", "overdraw.on"]
EXPRESSIONS = ["core_tempering_expression.blood_furnace", "core_tempering_expression.golden_bell",
               "core_tempering_expression.mountain_rending"]
SOURCES = ["TAL_VOID_VOID_NEEDLE#opt0", "TAL_VOID_VOID_NEEDLE#opt1", "TAL_VOID_VOID_NEEDLE#opt2",
           "improvised.attack", "natural.iron_fist_sphere"]
RIDER = re.compile(r"\.rider\.[0-9a-f]{8}\.")


def selector(source_id):
    """The compiled selector without the character hash this copy compiled under."""
    parts = RIDER.sub(".rider.*.", source_id).split(".")
    return ".".join(parts[2:]) if len(parts) > 2 else source_id


def listing(rows):
    return [selector(r["combat"]["source_definition_id"]) for r in rows
            if (r.get("combat") or {}).get("source_definition_id")]


@pytest.mark.parametrize("locked_expression", [False, True, "legacy"])
def test_option_listing_reaches_sheet_and_real_table_menu_after_reload(tmp_path, locked_expression):
    """Every printed option is listed, once, in order and at its stated cost.

    Presence, count, order, cost and economy are checked as ids and numbers so
    this file also runs on the scrambled public copy; the wording of the same
    options is checked in tests/test_option_tooltips_printed.py.
    """
    parts = option_match(tmp_path, locked_expression)
    sheet_ids = listing(parts["buttons"])
    assert [i for i in sheet_ids if i.startswith("open_the_gate.")] == GATE
    assert [i for i in sheet_ids if i.startswith("overdraw.")] == OVERDRAW
    assert len([i for i in sheet_ids if i.startswith("shape.")]) == 2
    augments = [i for i in sheet_ids if i.startswith("DARK_BASE_DARKNESS.toggle.")]
    assert len(augments) == 1 and not augments[0].endswith(".none")
    toggles = [i for i in sheet_ids if ".rider." in i and i.endswith(".on.toggle")]
    assert [i.split(".rider.")[0] for i in toggles] == SOURCES
    assert [i for i in sheet_ids if i.startswith("core_tempering_expression.")] == (
        EXPRESSIONS if locked_expression else [])

    menu = parts["state"]["menu"]["actions"]
    menu_ids = {selector(row["source_definition_id"]): row for row in menu}
    assert sorted(i for i in menu_ids if i.startswith("open_the_gate.")) == sorted(GATE)
    assert sorted(i for i in menu_ids if i.startswith("overdraw.")) == sorted(OVERDRAW)
    assert len([i for i in menu_ids if i.startswith("shape.")]) == 2
    assert len([i for i in menu_ids if i.startswith("DARK_BASE_DARKNESS.toggle.")]) == 2
    assert len([i for i in menu_ids if i.endswith(".toggle.none")]) == 1
    # The table menu must carry the same Core Tempering Expressions the sheet
    # offers, or a locked Body-Refining character loses real choices at the table.
    assert sorted(i for i in menu_ids if i.startswith("core_tempering_expression.")) == sorted(
        EXPRESSIONS if locked_expression else [])
    assert sorted(i for i in menu_ids if ".rider." in i and i.endswith(".on.toggle")) == [
        source + ".rider.*.on.toggle" for source in sorted(SOURCES)]
    for source in SOURCES:
        toggle = menu_ids[source + ".rider.*.on.toggle"]
        assert (toggle.get("economy"), toggle.get("cost_label")) == ("NONE", "Free")
        paid = menu_ids[source + ".rider.*.payment.0"]
        assert (paid.get("economy"), paid.get("cost_label")) == ("NONE", "Free")
        assert paid["label"].endswith(": 2 CP")

    # One row per candidate (no row dropped, none offered twice) in the order the
    # table persisted, and the reload lists the same rows in the same order.
    candidates = [row["options"][0]["candidate_id"] for row in menu]
    assert candidates == sorted(candidates) and len(set(candidates)) == len(candidates)
    resumed = TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(parts["mid"])
    listing_of = lambda rows: [(row["source_definition_id"], row["label"], row.get("economy"),
                                [o["candidate_id"] for o in row["options"]]) for row in rows]
    assert listing_of(resumed["menu"]["actions"]) == listing_of(menu)

    if locked_expression == "legacy":
        sealed = [a for a in parts["combat"]._load_session(parts["mid"]).engine.action_catalog.values()
                  if a.owner_id == OWNER and a.parameters.get("cte_choice")]
        assert len(sealed) == 3
        assert not [a for a in sealed if "setting_lifetime" in a.parameters]


def test_node_sheet_builder_rejects_explicitly_empty_real_rows(tmp_path):
    rows_file = tmp_path / "sol155-rows.json"
    rows_file.write_text("[]")
    result = subprocess.run(
        ["node", "tests/option_tooltips.test.mjs", str(rows_file)], cwd=ROOT,
        text=True, capture_output=True)
    assert result.returncode != 0
    assert "Real row missing" in result.stdout + result.stderr
