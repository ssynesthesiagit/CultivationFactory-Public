from pathlib import Path

import pytest
from types import SimpleNamespace

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_darkness_and_stealth import ME, QI, _fight, _do
from tests.test_factory_live_match import _install


@pytest.mark.parametrize("mode,expected", [("MANUAL", []), ("SUGGESTED", []), ("MANUAL_AI_BRIDGE", []),
                                          ("LOCAL_AUTO", ["Hungry Darkness"]), ("API_AUTO", ["Hungry Darkness"]), (None, [])])
def test_unchosen_shape_matches_controller_and_table_marker(mode, expected):
    engine = _fight()
    engine.typed_control_modes = {ME: mode} if mode else {}
    entries = TabletopService._shapes(None, engine)[ME]
    active = [option["label"] for entry in entries for option in entry["options"] if option["active"]]
    assert active == (["Hungry Darkness"] if expected else ["plain Darkness"])
    before = engine.state.actors[ME].resources[QI]
    _do(engine, "Darkness", at=(7, 6))
    zone = next(z for z in engine.state.zones.values() if z.active)
    assert zone.trigger_profile["talents"] == expected
    assert engine.state.actors[ME].resources[QI] == before


def test_explicit_player_shape_and_augment_both_survive_in_zone(monkeypatch):
    from tests import test_darkness_and_stealth as darkness

    sheet = darkness._sheet()
    sheet["spheres_and_talents"]["learned_talent_record_ids"].append("TAL_DARK_DIRECTIONAL_DARKNESS")
    monkeypatch.setattr(darkness, "_sheet", lambda: sheet)
    engine = _fight()
    engine.typed_control_modes = {ME: "MANUAL"}
    _do(engine, "Shape Darkness: Hungry Darkness")
    _do(engine, "Darkness + Directional Darkness", at=(7, 6))
    zone = next(z for z in engine.state.zones.values() if z.active)
    assert zone.trigger_profile["talents"] == ["Hungry Darkness"]
    assert zone.trigger_profile["augments"] == ["Directional Darkness"]


def test_loaded_control_modes_reach_preview_without_writing_metadata(tmp_path):
    _install(tmp_path, "left")
    _install(tmp_path, "right")
    combat = CombatService(Path(__file__).resolve().parents[1], tmp_path)
    actor = FACTORY_ACTOR_PREFIX + "left"
    match = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"],
                                        control_modes={actor: "MANUAL"}, match_seed="C1-MODES")
    metadata = combat._metadata_path(match["match_id"])
    before = metadata.read_bytes()
    session = combat._load_session(match["match_id"])
    assert session.engine.typed_control_modes[actor] == "MANUAL"
    clone = combat._clone_engine(combat.source_root, session.engine)
    assert clone.typed_control_modes == session.engine.typed_control_modes
    assert clone.typed_control_modes is not session.engine.typed_control_modes
    assert metadata.read_bytes() == before


def test_legacy_zone_labels_are_enriched_without_mutating_the_presentation():
    profile = {"name": "Darkness", "talents": ["Hungry Darkness"]}
    presentation = {"zones": [{"source_definition_id": "directional", "trigger_profile": profile}]}
    engine = SimpleNamespace(action_catalog={"directional": SimpleNamespace(parameters={"typed": {
        "augments": ["directional"], "modifier": {"name": "Directional Darkness"}}})})
    labelled = TabletopService._label_zone_augments(presentation, engine)
    assert labelled["zones"][0]["trigger_profile"]["augments"] == ["Directional Darkness"]
    assert "augments" not in profile
    assert labelled["zones"][0] is not presentation["zones"][0]
    assert TabletopService._label_zone_augments(presentation, None) is presentation
