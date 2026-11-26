import pytest
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, immobilize_on_action, OWNER, FOE


def _claw_setup(setup):
    if setup not in {"climb", "speed_two"}:
        return immobilize_on_action(
            "Opportunity Attack" if setup == "paralyzed" else "Black-Claw Manifestation", setup)

    def prepare(bundles):
        from combat.canonical import canonical_sha256

        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        if setup == "climb":
            owner["actor_template"]["climb_speed_ft"] = 30
        else:
            action = next(a for a in owner["action_catalog"] if a["display_name"] == "Black-Claw Manifestation")
            action["parameters"]["typed"]["effects"][:0] = [
                {"type": "speed", "flat": 4 - owner["actor_template"]["speed_ft"],
                 "applies_to": "self", "expires_on": "UNTIL_REMOVED"},
                {"type": "speed", "halved": True, "applies_to": "self", "expires_on": "UNTIL_REMOVED"},
            ]
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)
    return prepare


def _add_roof(arena):
    # The owner's ground square (3,6) is just outside the building's south wall.
    arena.update(to_battlefield(normalize_map({
        "display_name": "Black-Claw climb yard", "width_squares": 12, "height_squares": 12,
        "background": {"style": "wood"},
        "walls": [{"shape": "rect", "points": [[1, 1], [6, 5]], "filled": False, "height_ft": 10}],
        "roofs": {"enabled": True, "height_ft": 10},
    })))


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("setup", [None, "grappled", "restrained", "pinned", "paralyzed", "climb", "speed_two"])
def test_black_claw_opportunity_hit_choice_and_step_commit_reload(tmp_path, auto_turn, setup):
    """The landed attack earns a step only as far as usable native movement permits.

    A paralyzed reactor cannot land the attack at all (lock7-punishment-aegis).
    """
    can_step = setup in {None, "climb"}
    step_id = "cell:3,6,1" if setup == "climb" else "cell:2,6"
    combat, table, mid, send, commit = fixture(tmp_path, ["TAL_DAEMONIC_CULTIVATION_DEMON_SEED",
                                                       "TAL_DAEMONIC_CULTIVATION_BLACK_CLAW_MANIFESTATION"], foe_ac=0, seed="R1I-CLAW",
        bundle_transform=_claw_setup(setup), arena_edit=_add_roof if setup == "climb" else None)
    commit(candidate(table, mid, "Demon Seed"))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(candidate(table, mid, "Black-Claw Manifestation"))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    menu = table.state(mid)["menu"]
    cid = next(o["candidate_id"] for o in menu["moves"] if o["destination"] == {"x": 4, "y": 8})
    if auto_turn:
        force_ai_candidate(combat, mid, FOE, cid)
    engine = combat._load_session(mid).engine
    mover = engine.state.actors[OWNER]
    if setup == "climb":
        from combat import flight, roof_movement

        assert mover.position.z == 0 and flight.profile(engine, mover).speed_ft == 0
        assert roof_movement.profile(engine, mover).speed_ft == 30
    elif setup == "speed_two":
        assert engine._effective_speed(mover) == 2
    before = engine.state.model_dump(mode="json")
    answers, seen = [], []
    for _ in range(12):
        result = send(cid, answers, auto=auto_turn)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        source = p["context"]["reaction_source_id"]
        seen.append(source)
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        answer = {**p["context"], "selection": "USE"}
        if p.get("choice"):
            if source.endswith("black_claw"):
                answer["option_ids"] = ["move"]
            elif source.endswith("rider_step"):
                assert can_step, p  # no five-foot destination at effective Speed 2
                if setup is None:
                    # The separate exemption sentence also names Opportunity Attacks.
                    assert "Opportunity Attack" in p["moment"].partition(". No extra action")[0]
                offered = {o["id"]: o["label"] for o in p["choice"]["options"]}
                assert "2,6" in offered["cell:2,6"]
                if setup == "climb":
                    assert offered[step_id] == "Climb to 3,6 at 5 feet altitude (5 feet of movement)"
                    assert "cell:3,6,2" not in offered  # the ordinary Climb Speed cannot enlarge the grant
                answer["option_ids"] = [step_id]
            else:
                answer["option_ids"] = [p["choice"]["options"][0]["id"]]
        answers.append(answer)
    assert result["status"] == "COMMITTED"
    assert ("choice:needle.black_claw" in seen) == (setup != "paralyzed") and ("choice:needle.rider_step" in seen) == can_step, (
        seen, [e.payload for e in combat._load_session(mid).engine.events if e.event_type == "ATTACK_ROLLED"])
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = loaded.engine.state.actors[OWNER]
    recent = [e for e in loaded.engine.events if e.sequence > before["event_sequence"]]
    if setup == "paralyzed":
        assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER for e in recent)
        assert not any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == OWNER for e in recent)
        assert loaded.engine.state.actors[FOE].current_hp == before["actors"][FOE]["current_hp"]
    expected = before["actors"][OWNER]["position"]
    if can_step:
        expected = {"x": 3, "y": 6, "z": 1} if setup == "climb" else {"x": 2, "y": 6}
    assert owner.position.model_dump(mode="json") == expected
    assert owner.movement_remaining_ft == before["actors"][OWNER]["movement_remaining_ft"]
    moves = [e for e in recent if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER]
    if setup == "climb":
        move, = moves
        assert move.payload["movement_mode"] == "climb"
        assert move.payload["granted_cost_ft"] == 5
    elif not can_step:
        assert not moves
        assert loaded.engine._effective_speed(owner) == (2 if setup == "speed_two" else 0)
        if setup not in {"speed_zero", "speed_two"}:
            assert any(c.condition_id == "condition:typed." + setup for c in owner.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_black_claw_step_respects_effective_zero_speed_off_turn(tmp_path):
    test_black_claw_opportunity_hit_choice_and_step_commit_reload(tmp_path, False, "speed_zero")
