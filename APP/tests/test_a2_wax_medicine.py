"""Medicinal Wax through service transactions, table choices and cold replay."""
import pytest

from combat.ext.wax_medicine import PREFIX
from tests.test_r5i_integration import (
    PLAYER, OTHER, act, answer, candidate, check_reload, fixture, seed, turn,
)

MEDICINE = "TAL_WAX_MEDICINAL_WAX"


def setup(bundle, other):
    for kind in ("force", "fire", "poison"):
        seed(other, "Test " + kind, [{"type": "save", "ability": "dex", "dc": "technique_save_dc",
              "on_fail": [{"type": "damage", "flat": 20, "damage_types": [kind]}], "on_success": []}])
    seed(other, "Test damage", [{"type": "damage", "flat": 20, "damage_types": ["force"]}])
    seed(other, "Test zero", [{"type": "damage", "flat": 0, "damage_types": ["force"]}])
    seed(other, "Test disease", [{"type": "save", "ability": "con", "dc": "technique_save_dc",
          "on_fail": [{"type": "condition", "condition": "disease"}], "on_success": []}])


def prepare(combat, table, mid, base, target, preparation):
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
               if c.display_name == base and (target in c.target_ids or (target == PLAYER and not c.target_ids)))
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = act(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    assert all(name in result["reaction"]["moment"] for name in ("Medicinal Wax", base, "Wax Keeper"))
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert act(table, mid, cid, [answer(result, options=[preparation])])["status"] == "COMMITTED"


@pytest.mark.parametrize("base,feature", [("Seal Wound", "TAL_WAX_SEAL_WOUND"), ("Waxen Shell", "TAL_WAX_WAXEN_SHELL")])
@pytest.mark.parametrize("preparation", ["cooling", "stimulating", "numbing"])
@pytest.mark.parametrize("target", [PLAYER, OTHER])
def test_mandatory_preparation_uses_exact_printed_clock_and_survives_reload(tmp_path, base, feature, preparation, target):
    combat, table, mid = fixture(tmp_path, [feature, MEDICINE], allied=True)
    turn(table, mid, PLAYER)
    before = combat._load_session(mid).engine.state.actors[PLAYER].resources["resource:core.qi"]
    engine = combat._load_session(mid).engine
    speed = engine._effective_speed(engine.state.actors[target])
    movement = engine.state.actors[target].movement_remaining_ft
    prepare(combat, table, mid, base, target, preparation)
    engine = check_reload(combat, mid, tmp_path)
    actor = engine.state.actors[target]
    if preparation == "stimulating":
        assert engine._effective_speed(actor) == speed + 10
        assert actor.movement_remaining_ft == movement + (10 if target == PLAYER else 0)
    condition = next(c for c in actor.conditions.values() if c.condition_id == PREFIX + preparation)
    clock = actor if preparation == "stimulating" else engine.state.actors[PLAYER]
    assert condition.expires_on == f"END_OF_TURN_AT:{clock.entity_id}:{clock.turns_started + 1}"
    assert engine.state.actors[PLAYER].resources["resource:core.qi"] == before - 1
    assert not any("Medicinal Wax" in c.display_name for c in engine.legal_candidates())
    assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    assert any(c.condition_id == PREFIX + preparation for c in check_reload(combat, mid, tmp_path).state.actors[target].conditions.values())
    turn(table, mid, clock.entity_id)
    assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    assert not any(c.condition_id == PREFIX + preparation for c in check_reload(combat, mid, tmp_path).state.actors[target].conditions.values())
    if preparation == "stimulating":
        engine = check_reload(combat, mid, tmp_path)
        assert engine._effective_speed(engine.state.actors[target]) == speed


@pytest.mark.parametrize("kind", ["fire", "poison", "disease"])
def test_cooling_skips_unrelated_save_then_consumes_only_next_matching_save(tmp_path, kind):
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_WAXEN_SHELL", MEDICINE], configure=setup)
    turn(table, mid, PLAYER)
    prepare(combat, table, mid, "Waxen Shell", PLAYER, "cooling")
    turn(table, mid, OTHER)
    assert act(table, mid, candidate(combat, mid, "Test force", PLAYER))["status"] == "COMMITTED"
    assert any(c.condition_id == PREFIX + "cooling" for c in check_reload(combat, mid, tmp_path).state.actors[PLAYER].conditions.values())
    start = combat._load_session(mid).engine.state.event_sequence
    assert act(table, mid, candidate(combat, mid, "Test " + kind, PLAYER))["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    saves = [e for e in engine.events if e.sequence > start and e.event_type == "SAVE_ROLLED"]
    assert saves and saves[-1].payload["mode"] == "ADVANTAGE"
    assert not any(c.condition_id == PREFIX + "cooling" for c in engine.state.actors[PLAYER].conditions.values())
    start = engine.state.event_sequence
    assert act(table, mid, candidate(combat, mid, "Test " + kind, PLAYER))["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    saves = [e for e in engine.events if e.sequence > start and e.event_type == "SAVE_ROLLED"]
    assert saves[-1].payload["mode"] == "NORMAL"


def test_numbing_reduces_exactly_one_positive_packet_including_temporary_hp(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_WAXEN_SHELL", MEDICINE], configure=setup)
    turn(table, mid, PLAYER)
    prepare(combat, table, mid, "Waxen Shell", PLAYER, "numbing")
    turn(table, mid, OTHER)
    assert act(table, mid, candidate(combat, mid, "Test zero", PLAYER))["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert any(c.condition_id == PREFIX + "numbing" for c in engine.state.actors[PLAYER].conditions.values())
    for expected in (16, 20):
        actor = engine.state.actors[PLAYER]
        before = actor.current_hp + actor.temporary_hp
        assert act(table, mid, candidate(combat, mid, "Test damage", PLAYER))["status"] == "COMMITTED"
        engine = check_reload(combat, mid, tmp_path)
        actor = engine.state.actors[PLAYER]
        assert before - actor.current_hp - actor.temporary_hp == expected
        assert not any(c.condition_id == PREFIX + "numbing" for c in actor.conditions.values())


def test_medicine_is_inert_without_owned_talent(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_WAXEN_SHELL"])
    turn(table, mid, PLAYER)
    assert act(table, mid, candidate(combat, mid, "Waxen Shell"))["status"] == "COMMITTED"
    assert not any(c.condition_id.startswith(PREFIX) for c in check_reload(combat, mid, tmp_path).state.actors[PLAYER].conditions.values())


def test_stimulating_refresh_does_not_grant_a_second_movement_allowance(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_WAXEN_SHELL", MEDICINE])
    turn(table, mid, PLAYER)
    prepare(combat, table, mid, "Waxen Shell", PLAYER, "stimulating")
    assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    turn(table, mid, PLAYER)
    before = combat._load_session(mid).engine.state.actors[PLAYER].movement_remaining_ft
    prepare(combat, table, mid, "Waxen Shell", PLAYER, "stimulating")
    engine = check_reload(combat, mid, tmp_path)
    actor = engine.state.actors[PLAYER]
    assert actor.movement_remaining_ft == before
    assert len([c for c in actor.conditions.values() if c.condition_id == PREFIX + "stimulating"]) == 1


def test_ai_caster_chooses_a_preparation_without_player_prompt(tmp_path):
    from tests.test_r5i_integration import pin_ai

    combat, table, mid = fixture(tmp_path, ["TAL_WAX_WAXEN_SHELL", MEDICINE])
    turn(table, mid, PLAYER)
    pin_ai(combat, mid, PLAYER, candidate(combat, mid, "Waxen Shell"))
    assert table.auto_step(mid, 0, [])["status"] == "COMMITTED"
    actor = check_reload(combat, mid, tmp_path).state.actors[PLAYER]
    assert any(c.condition_id == PREFIX + "numbing" for c in actor.conditions.values())


def test_canceled_dex_save_preserves_cooling_until_an_actual_matching_roll(tmp_path, monkeypatch):
    from combat import ext
    from combat.gate2_runtime_models import Position
    from tests.test_lock_choices import move

    def configure(bundle, other):
        setup(bundle, other)
        seed(other, "Test canceled fire", [{"type": "save", "ability": "dex", "dc": "technique_save_dc",
             "on_fail": [{"type": "damage", "flat": 20, "damage_types": ["fire"]}], "on_success": []}])
        other["action_catalog"][-1]["range_ft"] = 5
        other["action_catalog"][-1]["parameters"]["typed"]["range_ft"] = 5

    def escape(engine, subject, intent, context):
        if context.get("source_id") != "test:Test canceled fire":
            return None
        move(engine, subject, Position(x=1, y=6))
        return {"mode": "ADVANTAGE"}

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "before_dex_save", [*ext._HOOKS.get("before_dex_save", []), escape])
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_WAXEN_SHELL", MEDICINE], configure=configure)
    turn(table, mid, PLAYER)
    prepare(combat, table, mid, "Waxen Shell", PLAYER, "cooling")
    turn(table, mid, OTHER)
    before = combat._load_session(mid).engine.state.event_sequence
    assert act(table, mid, candidate(combat, mid, "Test canceled fire", PLAYER))["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert engine.state.actors[PLAYER].position == Position(x=1, y=6)
    assert not any(e.event_type == "SAVE_ROLLED" and e.sequence > before for e in engine.events)
    assert any(c.condition_id == PREFIX + "cooling" for c in engine.state.actors[PLAYER].conditions.values())
    assert act(table, mid, candidate(combat, mid, "Test fire", PLAYER))["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert not any(c.condition_id == PREFIX + "cooling" for c in engine.state.actors[PLAYER].conditions.values())
