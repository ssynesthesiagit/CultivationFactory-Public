"""AI build choices at the table boundary, including committed reload and legacy replay."""
import copy

import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.ext.bodya_body_refining import CHOICE_CONDITION
from tests.h1_support import ROOT
from tests.test_auto_bodya import BODY_REFINING_SHEET
from tests.test_setting_choices import _install

LEFT, RIGHT = FACTORY_ACTOR_PREFIX + "sol98-left", FACTORY_ACTOR_PREFIX + "sol98-right"


def _fight(tmp_path, mode="LOCAL_AUTO", recorded=None):
    sheet = copy.deepcopy(BODY_REFINING_SHEET)
    if recorded:
        sheet["path_and_subpath"]["core_tempering_expression"] = recorded
    _install(tmp_path, "sol98-left", sheet)
    _install(tmp_path, "sol98-right", BODY_REFINING_SHEET)
    combat = CombatService(ROOT, tmp_path)
    mid = combat.create_factory_match(project_ids=["sol98-left"], opponent_actor_ids=[RIGHT],
        control_modes={LEFT: mode, RIGHT: mode}, match_seed="SOL98", maximum_rounds=2)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def _expressions(engine):
    return {aid: [c.data["expression"] for c in actor.conditions.values()
                  if c.condition_id == CHOICE_CONDITION]
            for aid, actor in engine.state.actors.items()}


@pytest.mark.parametrize("mode", ["LOCAL_AUTO", "API_AUTO"])
def test_ai_body_refining_receives_expression_before_first_table_action_and_after_commit_reload(tmp_path, mode):
    combat, table, mid = _fight(tmp_path, mode)
    assert _expressions(combat._load_session(mid).engine) == {LEFT: ["blood_furnace"], RIGHT: ["blood_furnace"]}
    if mode == "API_AUTO":
        # Verify the API-controlled initialization without making a provider call.
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    state = table.state(mid)
    result = table.auto_step(mid, state["last_sequence"], [])
    assert result["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert _expressions(reloaded.engine) == {LEFT: ["blood_furnace"], RIGHT: ["blood_furnace"]}
    assert reloaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("mode", ["LOCAL_AUTO", "API_AUTO"])
@pytest.mark.parametrize("recorded", ["Golden Bell Circulation", "mountain_rending"])
def test_ai_default_preserves_recorded_body_refining_expression(tmp_path, mode, recorded):
    combat, _, mid = _fight(tmp_path, mode, recorded)
    expected = "golden_bell" if recorded == "Golden Bell Circulation" else recorded
    assert _expressions(combat._load_session(mid).engine)[LEFT] == [expected]


@pytest.mark.parametrize("mode", ["MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"])
def test_player_keeps_all_core_tempering_choices_without_automatic_selection(tmp_path, mode):
    combat, table, mid = _fight(tmp_path, mode)
    engine = combat._load_session(mid).engine
    assert _expressions(engine) == {LEFT: [], RIGHT: []}
    choices = [c for c in engine.legal_candidates() if c.display_name.startswith("Core Tempering Expression:")]
    assert len(choices) == 3
    choice = next(c for c in choices if "Mountain-Rending" in c.display_name)
    state = table.state(mid)
    result = table.act(mid, choice.candidate_id, choice.decision_id, choice.state_version, state["last_sequence"], [])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert _expressions(loaded.engine)[choice.actor_id] == ["mountain_rending"]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_ai_setting_defaults_support_other_condition_choices_without_ability_specific_logic():
    from combat.ext.setting_choices import install_ai_setting_defaults
    from tests.test_auto_bodya import ME, _engine
    from combat.factory_compiler import compile_character

    engine = _engine(compile_character(BODY_REFINING_SHEET, actor_id=ME))
    engine.typed_control_modes = {ME: "LOCAL_AUTO"}
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and
                  a.parameters.get("ai_setting_default"))
    other = {"condition_id": "condition:test.other_build_choice", "source_definition_id": "test:other_feature",
             "data": {"choice": "first", "label": "Other feature: first choice"}}
    engine.action_catalog["action:test.other_selector"] = action.model_copy(update={
        "source_definition_id": "action:test.other_selector",
        "parameters": {**action.parameters, "ai_setting_default": other}})
    install_ai_setting_defaults(engine)
    assert any(c.condition_id == other["condition_id"] and c.data["choice"] == "first"
               for c in engine.state.actors[ME].conditions.values())
    before = len(engine.events)
    install_ai_setting_defaults(engine)
    assert len(engine.events) == before, "repeated installation must not replace choices or emit events"


def test_stock_saved_ai_continuation_is_byte_identical_with_shared_defaults_disabled(monkeypatch):
    from combat import ext
    from tests.test_hunt32_inert_replay import _capture

    enabled = _capture()
    for point, callbacks in list(ext._HOOKS.items()):
        monkeypatch.setitem(ext._HOOKS, point, [f for f in callbacks
            if f.__module__ != "combat.ext.setting_choices"])
    assert _capture() == enabled


def test_legacy_sealed_selector_without_opt_in_does_not_gain_ai_expression():
    from combat.factory_compiler import compile_character
    from combat.ext.setting_choices import install_ai_setting_defaults
    from tests.test_auto_bodya import ME, _engine

    bundle = compile_character(BODY_REFINING_SHEET, actor_id=ME)
    for action in bundle["action_catalog"]:
        action["parameters"].pop("ai_setting_default", None)
    engine = _engine(bundle)
    engine.typed_control_modes = {ME: "LOCAL_AUTO"}
    before = engine.state.model_dump(mode="json")
    events = len(engine.events)
    install_ai_setting_defaults(engine)
    assert engine.state.model_dump(mode="json") == before
    assert len(engine.events) == events
