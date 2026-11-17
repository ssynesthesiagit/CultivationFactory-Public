"""Wax menu regressions through table selection, commit, reload and replay."""

import pytest

from tests.test_r5i_integration import (
    AN, OTHER, PLAYER, act, answer, candidate, check_reload, fixture, mark, pin_ai, seed, turn,
)

SEAL = f"condition:typed.mark.wax_seal.{PLAYER}"


def sealed(engine, aid):
    return any(c.condition_id == SEAL for c in engine.state.actors[aid].conditions.values())


def test_smoke_puff_selects_isolated_form_and_preserves_other_wax(tmp_path):
    def configure(bundle, other):
        seed(bundle, "Seed Wax", [mark("Wax Seal")])

    combat, table, mid = fixture(tmp_path, ["TAL_WAX_MOLD_WAX"], configure=configure)
    turn(table, mid, PLAYER)
    assert act(table, mid, candidate(combat, mid, "Seed Wax", OTHER))["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    cid = next(c.candidate_id for c in engine.legal_candidates()
               if c.display_name.startswith("Mold Wax: Set Shape")
               and all(engine._distance_actor_to_cell(a, c.destination) > 20
                       for a in engine.state.actors.values()))
    assert act(table, mid, cid)["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    form = next(z for z in engine.state.zones.values() if z.active and "TAL_WAX_MOLD_WAX" in z.source_definition_id)
    assert all(min(engine._distance_actor_to_cell(a, cell) for cell in form.affected_cells) > 5
               for a in engine.state.actors.values())
    cid = candidate(combat, mid, "Kindle Wax: Smoke Puff (choose wax)")
    before = engine.state.model_dump(mode="json")
    result = act(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    assert "Smoke Puff" in result["reaction"]["moment"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert act(table, mid, cid, [answer(result, options=[f"form:{form.zone_id}"])])["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert not engine.state.zones[form.zone_id].active
    assert sealed(engine, OTHER)
    smoke = [z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("wax_smoke_edge")]
    assert len(smoke) == 1 and smoke[0].center == form.center
    assert smoke[0].trigger_profile["obscured"] == "light"
    assert engine.state.actors[PLAYER].resources == before["actors"][PLAYER]["resources"]


@pytest.mark.parametrize("recipient", [OTHER, PLAYER])
def test_candleflare_can_select_ally_or_self_and_consume_exact_seal(tmp_path, recipient):
    def configure(bundle, other):
        seed(bundle, "Seed Wax", [{"type": "wax_aimed", "effects": [mark("Wax Seal")]}], target="ALLY_OR_SELF")

    combat, table, mid = fixture(tmp_path, ["TAL_WAX_PRESS_SEAL"], allied=True, configure=configure)
    turn(table, mid, PLAYER)
    for aid in (PLAYER, OTHER):
        assert act(table, mid, candidate(combat, mid, "Seed Wax", aid))["status"] == "COMMITTED"
    cid = candidate(combat, mid, "Kindle Wax: Candleflare (ally or self)", recipient)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = act(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    assert "Candleflare" in result["reaction"]["moment"]
    assert act(table, mid, cid, [answer(result, options=[f"seal:{OTHER}"])])["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert sealed(engine, PLAYER) and not sealed(engine, OTHER)
    assert engine.state.actors[recipient].current_hp < before["actors"][recipient]["current_hp"]
    for aid in ({PLAYER, OTHER, AN} - {recipient}):
        assert engine.state.actors[aid].current_hp == before["actors"][aid]["current_hp"]
    assert engine.state.actors[PLAYER].resources == before["actors"][PLAYER]["resources"]


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("accept", [False, True])
def test_press_seal_non_ally_consent_without_save_on_manual_and_ai_turns(tmp_path, auto_turn, accept):
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_PRESS_SEAL"])
    turn(table, mid, PLAYER)
    cid = candidate(combat, mid, "Seal a Willing Creature (Press Seal) (willing creature)", OTHER)
    if auto_turn:
        pin_ai(combat, mid, PLAYER, cid)
    send = lambda answers=(): table.auto_step(mid, 0, list(answers)) if auto_turn else act(table, mid, cid, answers)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reactor_id"] == OTHER
    assert all(name in result["reaction"]["moment"] for name in ("Press Seal", "Wax Keeper", "Sound Guest"))
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([answer(result, options=["accept" if accept else "refuse"])])["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert sealed(engine, OTHER) == accept
    new_events = [e for e in engine.events if e.sequence > before["event_sequence"]]
    assert not any(e.event_type == "SAVE_ROLLED" for e in new_events)
    assert engine.state.actors[OTHER].reaction_available == before["actors"][OTHER]["reaction_available"]
    assert engine.state.actors[PLAYER].resources["resource:core.qi"] == before["actors"][PLAYER]["resources"]["resource:core.qi"] - 1


def test_press_seal_ai_non_ally_refuses_automatically(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_PRESS_SEAL"])
    turn(table, mid, PLAYER)
    combat.set_controller_mode(mid, actor_id=OTHER, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.event_sequence
    cid = candidate(combat, mid, "Seal a Willing Creature (Press Seal) (willing creature)", OTHER)
    assert act(table, mid, cid)["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert not sealed(engine, OTHER)
    assert not any(e.event_type == "SAVE_ROLLED" for e in engine.events if e.sequence > before)


def test_new_kindle_selections_require_owned_wax(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_PRESS_SEAL"], allied=True)
    turn(table, mid, PLAYER)
    names = {c.display_name for c in combat._load_session(mid).engine.legal_candidates()}
    assert "Kindle Wax: Smoke Puff (choose wax)" not in names
    assert "Kindle Wax: Candleflare (ally or self)" not in names
