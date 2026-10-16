"""Owner unlimited-concentration ruling, including real table commits and reloads."""
import copy
import json
import zipfile

import pytest

from combat import concentration, zones
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_auto_docket import ROOT, _sheet
from tests.test_multi_concentration import _engine


@pytest.mark.parametrize("cl", [1, 4, 5, 10, 15, 20])
def test_unlimited_distinct_techniques_at_every_level(cl):
    engine, actor = _engine(cl)
    assert concentration.limit_for_cl(cl) is None
    expected = [f"test:technique.{i}" for i in range(12)]
    for source in expected:
        assert concentration.free_slot(engine, actor)
        engine._start_concentration(actor, source)
    assert concentration.sources(actor) == expected
    engine._end_concentration(actor, "FAILED_DAMAGE_CHECK")
    assert concentration.sources(actor) == expected[:-1]
    engine._end_concentration(actor, "ENTITY_DEFEATED")
    assert concentration.sources(actor) == []


def test_sealed_sample_keeps_one_slot_in_a_mixed_factory_fight():
    engine, factory = _engine(1)
    actor = next(a for a in engine.state.actors.values() if not a.entity_id.startswith(FACTORY_ACTOR_PREFIX))
    assert concentration.limit(engine, actor) == 1
    for _ in range(12):
        engine._start_concentration(actor, "test:same")
        engine._start_concentration(factory, "test:same")
    assert concentration.sources(actor) == ["test:same"]
    assert concentration.held(actor) == []
    assert concentration.sources(factory) == ["test:same"] * 12
    engine._start_concentration(actor, "test:another")
    assert concentration.sources(actor) == ["test:another"]


@pytest.mark.parametrize("auto", [False, True])
def test_seven_same_technique_casts_survive_table_commits_reload_and_replay(tmp_path, monkeypatch, auto):
    actors = [FACTORY_ACTOR_PREFIX + side for side in ("left", "right")]
    for side in ("left", "right"):
        sheet = copy.deepcopy(_sheet(["DARK_BASE_DARKNESS"]))
        sheet["identity"]["cultivation_level"] = 1
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "R13 concentration yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[9, 4]]}})
    mid = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[actors[1]],
        control_modes={a: "MANUAL" for a in actors}, arena_id="battlefield:map.r13-concentration-yard",
        match_seed="R13-CONCENTRATION")["match_id"]
    table = TabletopService(combat, tmp_path)
    owner = table.state(mid)["menu"]["actor_id"]
    real = combat.controller
    class CastDarkness:
        def choose_primary_action(self, context):
            candidate = next(c for c in context.legal_candidates if c.display_name.startswith("Darkness at "))
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    if auto:
        from combat import ext
        # Deliberately scripted recasts exercise automatic execution/persistence.
        # The stock AI's separate preference against redundant recasts stays intact.
        ext.effects()
        monkeypatch.setitem(ext._HOOKS, "ai_candidate_allowed", [h for h in ext._HOOKS["ai_candidate_allowed"]
            if h.__module__ != "combat.ext.ai_restraint"])
        combat.controller = CastDarkness()
        combat.set_controller_mode(mid, actor_id=owner, controller_mode="LOCAL_AUTO")
    for count in range(1, 8):
        state = table.state(mid)
        menu = state["menu"]
        assert menu["actor_id"] == owner
        if auto:
            result = table.auto_step(mid, state["last_sequence"])
        else:
            action = next(a for a in menu["actions"] if a["label"] == "Darkness")
            result = table.act(mid, action["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
        assert result["status"] == "COMMITTED"
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        actor = loaded.engine.state.actors[owner]
        assert len(concentration.sources(actor)) == count
        assert len(concentration.copies(actor, actor.concentration.source_definition_id)) == count
        assert len(zones.typed_zones(loaded.engine)) == count
        assert loaded.mechanical.replay()["status"] == "PASS"
        if count < 7:
            if auto:
                combat.set_controller_mode(mid, actor_id=owner, controller_mode="MANUAL")
            for _ in range(2):
                state = table.state(mid)
                menu = state["menu"]
                result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
                assert result["status"] == "COMMITTED"
            if auto:
                combat.set_controller_mode(mid, actor_id=owner, controller_mode="LOCAL_AUTO")
