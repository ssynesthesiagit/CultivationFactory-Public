"""SOL155: the real sheet and persisted table menu carry printed option rules."""
import os
import json
from pathlib import Path
import subprocess
import pytest

from combat import factory_compiler
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
    from combat import status_text, option_text, factory_compiler
    compiler_rules = {
        "TAL_DARK_NUMBING_DARKNESS": (
            "### Numbing Darkness - Darkness\nSynthetic Darkness-shaping talent."),
        "TAL_DARK_PERSISTENT_DARKNESS": (
            "#### Persistent Darkness\n"
            "Augment - 2 CP: The selected Darkness lasts without Concentration."),
    }
    rules = {**status_text.printed_rules(), **compiler_rules,
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
    path = tmp_path / "synthetic-option-rules.json"
    path.write_text(json.dumps(rules))
    monkeypatch.setattr(status_text, "RULES_TEXT_PATH", path)
    # Compilation has its own source reader: the heading selects area talents,
    # and the augment clause selects persistent-area options. Feeding only the
    # hover reader leaves both choices absent when source prose is withheld.
    monkeypatch.setattr(factory_compiler, "_RULES_TEXT_CACHE",
                        {**factory_compiler._rules_text(), **compiler_rules}, raising=False)
    option_text._names.cache_clear()
    yield
    option_text._names.cache_clear()


@pytest.mark.parametrize("locked_expression", [False, True, "legacy"])
def test_printed_options_reach_sheet_and_real_table_menu_after_reload(tmp_path, locked_expression):
    project = "15500000-0000-0000-0000-000000000000"
    owner_sheet = sheet()
    if locked_expression:
        owner_sheet["identity"] = {**owner_sheet["identity"], "path": "Body Refining"}
        owner_sheet["path_and_subpath"] = {"path_feature_record_ids": [
            "tianxia.path.body_refining.feature.core_tempering_expression"]}
    _install(tmp_path, project, owner_sheet)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    buttons = table.sheet(project)["buttons"]
    if isinstance(buttons, dict):
        buttons = buttons["buttons"]
    foe = "actor:factory.sol155-foe"
    owner_bundle = compile_character(owner_sheet, actor_id=OWNER)
    if locked_expression == "legacy":
        # Pre-SOL155 sealed Core Tempering rows had this same contextual
        # description and cte_choice marker, but no setting_lifetime field.
        # Persist that catalog, rather than recompiling it on reload.
        for action in owner_bundle["action_catalog"]:
            if action["parameters"].get("cte_choice"):
                action["parameters"].pop("setting_lifetime")
                assert "permanent until a later Realm breakthrough" in action["parameters"]["setting_description"]
    mid = combat._finish_factory_match([owner_bundle, compile_character(sheet(), actor_id=foe)], [OWNER, foe],
        {OWNER: "team:a", foe: "team:b"}, {OWNER: {"x": 3, "y": 6}, foe: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER], [foe],
        control_modes={OWNER: "MANUAL", foe: "MANUAL"}, match_seed="SOL155", display_name="SOL155", maximum_rounds=5)["match_id"]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    state = table.state(mid)
    if combat._load_session(mid).engine.state.current_actor_id != OWNER:
        turn_menu = state["menu"]
        result = table.act(mid, turn_menu["end_turn"], turn_menu["decision_id"],
                           turn_menu["state_version"], state["last_sequence"], [])
        assert result["status"] == "COMMITTED"
        combat = CombatService(ROOT, tmp_path)
        state = TabletopService(combat, tmp_path).state(mid)
    assert combat._load_session(mid).engine.state.current_actor_id == OWNER
    if locked_expression == "legacy":
        sealed = [a for a in combat._load_session(mid).engine.action_catalog.values()
                  if a.owner_id == OWNER and a.parameters.get("cte_choice")]
        assert len(sealed) == 3
        assert all("setting_lifetime" not in a.parameters for a in sealed)
    menu = state["menu"]["actions"]
    expected = {
        "Open the Gate: Breath-Checking Strike": "cannot take Opportunity Attacks until the start of its next turn",
        "Open the Gate: Centerline Impact": "add your Proficiency Bonus to that damage",
        "Open the Gate: Hooking Step": "Move yourself 5 feet without provoking Opportunity Attacks",
        "Shape Darkness: Numbing Darkness": "Numbing Darkness",
        "Augment Darkness: Persistent Darkness": "without Concentration",
        "Overdraw: ready": "add bonus Ruin damage",
    }
    for rows in (buttons, menu):
        for label, effect in expected.items():
            matched = [r for r in rows if r["label"] == label]
            assert matched, (f"Missing option: {label}; "
                             f"reader={'sheet' if rows is buttons else 'table'}; "
                             f"darkness={[r['label'] for r in rows if 'Darkness' in r['label']]}; "
                             f"compiled={[a['display_name'] for a in owner_bundle['action_catalog'] if 'Darkness' in a['display_name']]}; "
                             f"tags={factory_compiler._talent_tags('TAL_DARK_NUMBING_DARKNESS')}; "
                             f"source={_darkness_compiler_inputs()}")
            row = matched[0]
            assert effect in row["description"]
            assert effect in row["hover"]["text"]
            assert row["description"].count(CHOICE_LINE) == 1
            assert row["hover"]["text"].count(CHOICE_LINE) == 1
    assert "When you Open a creature".lower() in printed_rules()["printed_option:Breath-Checking Strike"].lower()
    for rows in (buttons, menu):
        row = next(r for r in rows if r["label"].startswith("Nullifying Strike"))
        assert "The target makes a Constitution saving throw" in row["description"]
        assert "Cost: 2 cultivation points or 2 Stamina" in row["description"]
    for payload in (buttons, menu):
        # The sheet groups modifier choices; the table exposes each rider.
        nullifying = [r for r in payload if r["label"].startswith("Nullifying Strike")]
        assert nullifying
        if locked_expression:
            expressions = [r for r in payload if r["label"].startswith("Core Tempering Expression:")]
            assert len(expressions) == 3, [r["label"] for r in payload]
            for row in expressions:
                for text in (row["description"], row["hover"]["text"]):
                    assert "permanent until a later Realm breakthrough" in text
                    assert "cannot change it during this fight" in text
                    assert "stays selected until you change it" not in text
        for row in nullifying:
            for text in (row["description"], row["hover"]["text"]):
                assert "Failed Save:" in text
                evidence = row["label"].partition(" — ")[2]
                if evidence:
                    assert "Failed Save: " + evidence.rstrip(";") in text.replace("’", "'")


def _darkness_compiler_inputs():
    """Small failure receipt for source-dependent option compilation."""
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())["mechanics"]
    return {key: {field: authority.get(key, {}).get(field)
                  for field in ("activation", "duration", "area", "description", "split_into")}
            for key in ("DARK_BASE_DARKNESS", "TAL_DARK_NUMBING_DARKNESS")}


def test_node_sheet_and_table_builders():
    subprocess.run(["node", "tests/option_tooltips.test.mjs"], cwd=ROOT,
                   env={**os.environ, "SOL155_ROWS": json.dumps(rows())}, check=True)


def test_node_sheet_builder_rejects_explicitly_empty_real_rows():
    result = subprocess.run(
        ["node", "tests/option_tooltips.test.mjs"], cwd=ROOT,
        env={**os.environ, "SOL155_ROWS": "[]"}, text=True, capture_output=True)
    assert result.returncode != 0
    assert "Real row missing" in result.stdout + result.stderr


def test_inline_riders_use_their_own_printed_option_and_keep_cost_and_expiry():
    from combat.ext.foundation_sacred_body import REBUKE, rebuke_choices
    from combat.tabletop import engine_button_description
    info = {"owned_ids": {REBUKE}, "short": "sol155", "actor_id": OWNER, "numbers": {}}
    actions = rebuke_choices(info)
    push = next(a for a in actions if a.display_name.endswith("Push 5 ft"))
    text = engine_button_description(push.model_dump(mode="json"))
    assert text.startswith("push the target 5 feet if it is no more than one size larger than you.")
    assert "Cost: 1 Golden Sea Pulse" in text
    assert "cannot take Reactions against you" not in text
    frame = next(a for a in actions if a.display_name.endswith("Frame Advantage"))
    text = engine_button_description(frame.model_dump(mode="json"))
    assert text.startswith("you gain Advantage on the next eligible Saint-Body Frame resistance roll")
    assert "before the start of your next turn" in text
    assert "push the target 5 feet" not in text
