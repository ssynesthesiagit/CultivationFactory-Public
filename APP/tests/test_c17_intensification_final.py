"""Formula Intensification's optional movement completes the real table action."""
import json
import zipfile

import pytest
from tests.legacy_fight_support import legacy_zero_hp

pytestmark = pytest.mark.usefixtures("legacy_zero_hp")

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import test_riders_lane3 as alchemy
from tests.test_c17_bitter_final import OWNER, FOE
from tests.test_lock2_persistence import act
from combat import ext
from tests.r10_fixup_support import cast_sender, answer


@pytest.mark.parametrize("terminal", [False, True])
@pytest.mark.parametrize("choice", ["move", "stay", "decline", "auto"])
def test_intensification_final_choice_commit_reload(monkeypatch, tmp_path, terminal, choice):
    for project in ("aaaaaaaa", "bbbbbbbb"):
        owner = project == "aaaaaaaa"
        sheet = alchemy.H._sheet("tianxia.sphere.alchemy" if owner else None,
            [alchemy.INTENSIFY] if owner else [], alchemy.H.AXE_KIT, dc=alchemy.PASS, cl=10)
        sheet["identity"]["display_name"] = "Alchemist" if owner else "Practice Rival"
        sheet["ability_scores_and_statistics"]["hit_points"] = {
            "maximum": 80 if owner or not terminal else 1}
        archive = tmp_path / "portable_characters" / project / "current.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))

    def prepared(engine, kind, kwargs):
        if kind == "HOLD_POSITION_COMMITTED" and kwargs["actor_id"] == OWNER:
            engine._gain_resource(engine.state.actors[OWNER], alchemy.STOCK, 1, "test:stock")
    # The prepared-inventory hook joins the engine's own event subscribers: replacing the list
    # would switch off every other plug-in's event reader (combat/ext/life_state._events among
    # them), so a defeated creature never finalizes and the fight never ends.
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), prepared])
    service = CombatService(alchemy.H.ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "Formula yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    mid = service.create_factory_match(project_ids=["aaaaaaaa"], opponent_actor_ids=[FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, arena_id="battlefield:map.formula-yard",
        match_seed="C17-INTENSIFICATION-FINAL")["match_id"]
    table = TabletopService(service, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    before = service._load_session(mid).engine.state.model_copy(deep=True)
    name = "Field Formula: Numbing Smoke + Formula Intensification: Move Self"
    if choice == "auto":
        from tests.r1i_service_support import force_ai_candidate
        candidate = next(c for c in service._load_session(mid).engine.legal_candidates()
            if c.display_name.startswith(name + " at ") and c.destination.x == 4 and c.destination.y == 4)
        force_ai_candidate(service, mid, OWNER, candidate.candidate_id)
        result = table.auto_step(mid, table.state(mid)["last_sequence"])
    else:
        send = cast_sender(service, table, mid, name, at=(4, 4))
        paused = send()
        assert paused["status"] == "REACTION_REQUIRED", paused
        prompt = paused["reaction"]
        text = json.dumps(prompt)
        assert all(word in text for word in ("Formula Intensification", "Numbing Smoke", "Alchemist", "10"))
        # The paused transaction must not spend stock, deal damage or move yet.
        loaded = CombatService(alchemy.H.ROOT, tmp_path)._load_session(mid).engine
        assert loaded.state.actors[OWNER] == before.actors[OWNER]
        assert loaded.state.terminal_result is None
        # Reopen the choice with a fresh service before accepting/declining it.
        service = CombatService(alchemy.H.ROOT, tmp_path)
        table = TabletopService(service, tmp_path)
        send = cast_sender(service, table, mid, name, at=(4, 4))
        result = send([answer(prompt, "cell:1,4" if choice == "move" else "cell:3,4",
                              use=choice != "decline")])
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(alchemy.H.ROOT, tmp_path)._load_session(mid)
    engine, actor = loaded.engine, loaded.engine.state.actors[OWNER]
    events = [e for e in engine.events if e.sequence > before.event_sequence]
    assert actor.position.x == (1 if choice == "move" else 3)
    assert actor.position.y == 4
    assert actor.movement_remaining_ft == before.actors[OWNER].movement_remaining_ft
    assert actor.resources[alchemy.STOCK] == before.actors[OWNER].resources[alchemy.STOCK] - 1
    assert actor.resources["resource:core.stamina"] == before.actors[OWNER].resources["resource:core.stamina"] - 3
    assert not actor.turn_flags.get("disengaged")
    assert "spark_step_ignore_oa_from" not in actor.turn_flags
    assert len([e for e in events if e.event_type == "SAVE_ROLLED"]) == 1
    assert len([e for e in events if e.event_type == "DAMAGE_ROLLED"]) == 1
    moves = [e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER]
    assert len(moves) == int(choice == "move")
    assert not [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert (engine.state.terminal_result is not None) == terminal
    if moves:
        assert moves[0].sequence > max(e.sequence for e in events if e.event_type == "DAMAGE_COMMITTED")
        # Native granted movement records its own budget separately.
        assert moves[0].payload["cost_ft"] == 0
        assert moves[0].payload["granted_cost_ft"] == 10
        if terminal:
            assert moves[0].sequence > engine.state.terminal_result.event_sequence
    assert not getattr(engine, "_final_rider_active", False)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
