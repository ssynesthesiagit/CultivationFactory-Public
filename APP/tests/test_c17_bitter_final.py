"""Bitter Dregs' mandatory cost finishes the real table action, even at victory."""
import json
import zipfile

import pytest
from tests.legacy_fight_support import legacy_zero_hp

pytestmark = pytest.mark.usefixtures("legacy_zero_hp")

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests import test_riders_lane3 as alchemy
from tests.test_lock2_persistence import act
from combat import ext
from tests.r10_fixup_support import cast_sender

OWNER = FACTORY_ACTOR_PREFIX + "aaaaaaaa"
FOE = FACTORY_ACTOR_PREFIX + "bbbbbbbb"


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("case", ["terminal", "nonterminal", "failed_save", "plain"])
def test_bitter_backlash_finishes_once_and_reloads(monkeypatch, tmp_path, auto, case):
    for project in ("aaaaaaaa", "bbbbbbbb"):
        owner = project == "aaaaaaaa"
        sheet = alchemy.H._sheet("tianxia.sphere.alchemy" if owner else None,
                                 [alchemy.BITTER] if owner else [], alchemy.H.AXE_KIT,
                                 dc=alchemy.FAIL if case == "failed_save" else alchemy.PASS)
        sheet["identity"]["display_name"] = "Alchemist" if owner else "Practice Rival"
        sheet["ability_scores_and_statistics"]["hit_points"] = {
            "maximum": 80 if owner or case == "nonterminal" else 1}
        archive = tmp_path / "portable_characters" / project / "current.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))

    def prepared(engine, kind, kwargs):
        if kind == "HOLD_POSITION_COMMITTED" and kwargs["actor_id"] == OWNER:
            actor = engine.state.actors[OWNER]
            engine._gain_resource(actor, alchemy.DREG, 2, "test:prepared-dregs")
            engine._gain_resource(actor, alchemy.STOCK, 1, "test:prepared-stock")
    # The prepared-inventory hook joins the engine's own event subscribers: replacing the list
    # would switch off every other plug-in's event reader (combat/ext/life_state._events among
    # them), so a defeated creature never finalizes and the fight never ends.
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), prepared])
    service = CombatService(alchemy.H.ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "Dregs yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    mid = service.create_factory_match(project_ids=["aaaaaaaa"], opponent_actor_ids=[FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, arena_id="battlefield:map.dregs-yard",
        match_seed="C17-BITTER-FINAL")["match_id"]
    table = TabletopService(service, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    before = service._load_session(mid).engine.state.model_copy(deep=True)
    name = "Field Formula: Numbing Smoke" + ("" if case == "plain" else " + Bitter Dregs")
    send = cast_sender(service, table, mid, name, at=(4, 4))
    if auto:
        from tests.r1i_service_support import force_ai_candidate
        candidate = next(c for c in service._load_session(mid).engine.legal_candidates()
                         if c.display_name.startswith(name + " at ") and c.destination.x == 4
                         and c.destination.y == 4)
        force_ai_candidate(service, mid, OWNER, candidate.candidate_id)
        result = table.auto_step(mid, table.state(mid)["last_sequence"])
    else:
        result = send()
    assert result["status"] == "COMMITTED"
    loaded = CombatService(alchemy.H.ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    events = [e for e in engine.events if e.sequence > before.event_sequence]
    assert len([e for e in events if e.event_type == "SAVE_ROLLED"]) == 1
    assert len([e for e in events if e.event_type == "DAMAGE_ROLLED"]) == 1
    backlash = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and OWNER in e.target_ids]
    owed = case in ("terminal", "nonterminal")
    assert len(backlash) == int(owed)
    owner = engine.state.actors[OWNER]
    assert owner.current_hp == before.actors[OWNER].current_hp - (4 if owed else 0)
    assert owner.resources[alchemy.DREG] == before.actors[OWNER].resources[alchemy.DREG] - int(case != "plain")
    assert owner.resources[alchemy.STOCK] == before.actors[OWNER].resources[alchemy.STOCK] - int(case == "plain")
    assert owner.resources["resource:core.stamina"] == before.actors[OWNER].resources["resource:core.stamina"] - 1
    assert (engine.state.terminal_result is not None) == (case != "nonterminal")
    if owed:
        assert backlash[0].payload["damage_type"] == "POISON"
        assert backlash[0].payload["hp_damage"] == 4
        if case == "terminal":
            assert backlash[0].sequence > engine.state.terminal_result.event_sequence
    assert not getattr(engine, "_final_rider_active", False)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
