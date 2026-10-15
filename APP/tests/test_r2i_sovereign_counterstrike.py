"""Sovereign's independent free strike, including table preview/reload."""
import importlib

import pytest

from combat.ext.iron_fist_riders import SOVEREIGN_COUNTER_USED
from combat.gate2_runtime_models import ReactionDecision
from combat.gate5_service import CombatService

F = importlib.import_module("tests.test_r2i_sovereign_forms")
R, I, NAME, SOURCE = F.R, F.I, F.NAME, F.SOURCE
CHOICE = "choice:needle.sovereign_counterstrike"


def fixture(case="active", decline=False):
    engine = R._duel([] if case == "unowned" else [SOURCE, R.BREAKING], cl=15)
    if case not in ("unowned", "inactive"):
        R.A._use(engine, NAME, None)
    owner, foe = engine.state.actors[R.ME], engine.state.actors[R.FOE]
    if case == "old_bundle":
        for action in engine.action_catalog.values():
            action.parameters.get("iron_riders", {}).pop("sovereign_counterstrike", None)
    elif case == "other_caster":
        next(c for c in owner.conditions.values() if c.condition_id == "condition:typed.sovereign_iron_body").source_actor_id = R.FOE
    elif case == "incapacitated":
        R._incapacitate(engine)
    elif case == "expired":
        from combat.ext.effect_durations import sweep
        engine.state.round_number += 10
        sweep(engine, owner, "START_OF_TURN")
    elif case == "friendly":
        foe.team_id = owner.team_id
    elif case == "far":
        foe.position = foe.position.model_copy(update={"x": foe.position.x + 5})
    R._foe_turn(engine)
    owner.armor_class = 1000
    owner.reaction_available = False
    foe.armor_class = -50
    requests = []

    def provider(req):
        requests.append(req)
        selected = req["reaction_source_id"] == CHOICE and not decline
        return ReactionDecision(checkpoint=req["checkpoint"], reactor_id=req["reactor_id"],
                                reaction_source_id=req["reaction_source_id"], selection="USE" if selected else "DECLINE",
                                option_ids=("strike",) if selected else ()), None

    engine._gate4_reaction_provider = provider
    return engine, requests


def strikes(events):
    return [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == R.ME
            and e.source_definition_id.endswith(".sovereign_counterstrike")]


def test_counterstrike_once_per_round_no_reaction_and_normal_downstream_delivery():
    engine, requests = fixture()
    owner, foe = engine.state.actors[R.ME], engine.state.actors[R.FOE]
    R._resist(engine, R.FOE, "BLUDGEONING", "FORCE")
    # Denial of Reactions does not deny this independent no-Reaction strike.
    engine._apply_condition(owner, "condition:typed.reaction_denied", "test:no_reactions", R.FOE, expires_on="UNTIL_REMOVED")
    move = (owner.movement_remaining_ft, foe.movement_remaining_ft)
    R._foe_attacks(engine)
    assert len(strikes(engine.events)) == 1
    assert not owner.reaction_available
    assert owner.turn_flags[SOVEREIGN_COUNTER_USED] == engine.state.round_number
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == R.ME for e in engine.events)
    damage = R._committed(engine.events, R.FOE)
    assert damage and all(reduced == rolled for rolled, reduced, _ in damage)
    assert any(e.event_type == "PASSIVE_TRIGGERED" and NAME + " after " in e.payload.get("text", "") for e in engine.events)
    from combat.typed_executor import bears_mark
    assert bears_mark(foe, R.ME, "Opened")
    assert (owner.movement_remaining_ft, foe.movement_remaining_ft) == move
    for new_round in (False, True):
        if not new_round:
            engine.state.current_actor_id = R.ME
            engine.state.current_slot_index = engine.state.initiative_order.index(R.ME)
            engine._system_start_turn()
            R._foe_turn(engine)
            owner.armor_class = 1000
        foe.action_available = True
        if new_round:
            engine.state.round_number += 1
        R._foe_attacks(engine)
        assert len(strikes(engine.events)) == (2 if new_round else 1)


@pytest.mark.parametrize("case", ["inactive", "unowned", "old_bundle", "other_caster", "incapacitated", "expired", "friendly", "far", "ranged", "hit"])
def test_counterstrike_ownership_and_eligibility_gates(case):
    engine, requests = fixture(case)
    if case in ("friendly", "far", "ranged"):
        from combat.typed_executor import Context
        from combat.ext.iron_fist_riders import sovereign_counterstrike
        action = next(a for a in engine.action_catalog.values() if a.owner_id == R.FOE and ".weapon." in a.source_definition_id)
        ctx = Context(engine, engine.state.actors[R.FOE], action, None, action.parameters["typed"], [engine.state.actors[R.ME]])
        sovereign_counterstrike(ctx, engine.state.actors[R.ME], {"range_ft": 60} if case == "ranged" else {})
    else:
        if case == "hit":
            engine.state.actors[R.ME].armor_class = -50
        R._foe_attacks(engine)
    assert not strikes(engine.events)
    assert not any(req["reaction_source_id"] == CHOICE for req in requests)


def test_decline_preserves_use():
    engine, requests = fixture(decline=True)
    R._foe_attacks(engine)
    assert any(req["reaction_source_id"] == CHOICE for req in requests)
    assert SOVEREIGN_COUNTER_USED not in engine.state.actors[R.ME].turn_flags
    assert not strikes(engine.events)


def test_counterstrike_delivers_owned_forms_through_normal_hit_pipeline():
    engine, _ = fixture()
    R._open(engine)
    R._answer_options(engine, lambda req: req.get("legal_option_ids", [])[:1])
    R._foe_attacks(engine)
    assert len(strikes(engine.events)) == 1
    source = strikes(engine.events)[0].source_definition_id
    packets = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == source]
    assert len(packets) == 2  # natural strike and Breaking Knuckle, exactly once
    natural = engine.action_catalog[source[:-len(".sovereign_counterstrike")]]
    assert packets[1].payload["hp_damage"] == natural.parameters["typed"]["numbers"]["pb"]
    assert F.SOVEREIGN_USED in engine.state.actors[R.ME].turn_flags


@pytest.mark.parametrize("distance,expected", [(15, True), (20, False)])
def test_owned_unarmed_reach_includes_sovereigns_ten_feet(distance, expected):
    from combat.typed_executor import Context
    from combat.ext.iron_fist_riders import sovereign_counterstrike
    from combat.gate2_runtime_models import ActionIntent
    engine, requests = fixture()
    owner, foe = engine.state.actors[R.ME], engine.state.actors[R.FOE]
    foe.position = foe.position.model_copy(update={"x": owner.position.x + distance // 5, "y": owner.position.y})
    action = next(a for a in engine.action_catalog.values() if a.owner_id == R.FOE and ".weapon." in a.source_definition_id)
    intent = ActionIntent(intent_id="reach-test", decision_id="reach", candidate_id="reach", state_version=engine.state.state_version,
                          actor_id=R.FOE, target_ids=(R.ME,))
    ctx = Context(engine, foe, action, intent, action.parameters["typed"], [owner])
    sovereign_counterstrike(ctx, owner, {})
    assert bool(strikes(engine.events)) == expected
    assert any(req["reaction_source_id"] == CHOICE for req in requests) == expected


@pytest.mark.parametrize("turn", ["manual_enemy", "ai_enemy"])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("ordinary", ["USE", "DECLINE"])
def test_counterstrike_table_independent_choice_rollback_reload(tmp_path, turn, selection, ordinary):
    verify_table(tmp_path, turn, selection, ordinary)


def verify_table(tmp_path, turn, selection, ordinary, *, authority=None):
    combat, table, mid = F.table_fixture(tmp_path, authority=authority, foe_counter=turn == "own")
    send = (lambda answers: I.act(combat, table, mid, R.STRIKE, R.FOE, answers)) if turn == "own" else F.trigger(combat, table, mid, turn)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answers, offered, regular = [], [], []
    for _ in range(12):
        result = send(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": ordinary}
        if prompt.get("choice"):
            if prompt["context"]["reaction_source_id"] == CHOICE:
                offered.append(prompt)
                assert prompt["context"]["reactor_id"] == R.ME
                assert NAME in prompt["moment"] and ("Counter Palm" if turn == "own" else "Fu (Short Axe) attack") in prompt["moment"]
                assert all(combat._load_session(mid).engine.state.actors[aid].display_name in prompt["moment"] for aid in (R.ME, R.FOE))
                assert prompt["choice"]["allow_decline"]
                assert [o["id"] for o in prompt["choice"]["options"]] == ["strike"]
                answer.update(selection=selection, option_ids=["strike"] if selection == "USE" else [])
            else:
                answer.update(selection="DECLINE", option_ids=[])
        else:
            regular.append(prompt)
        answers.append(answer)
    assert result["status"] == "COMMITTED" and len(offered) == 1 and regular
    loaded = CombatService(R.ROOT, tmp_path)._load_session(mid)
    owner = loaded.engine.state.actors[R.ME]
    assert loaded.engine.state.model_dump(mode="json") == combat._load_session(mid).engine.state.model_dump(mode="json")
    assert (SOVEREIGN_COUNTER_USED in owner.turn_flags) == (selection == "USE")
    assert len(strikes(loaded.engine.events)) == (1 if selection == "USE" else 0)
    assert owner.reaction_available == (turn == "own" or ordinary == "DECLINE")
    for aid in (R.ME, R.FOE):
        assert loaded.engine.state.actors[aid].movement_remaining_ft == before["actors"][aid]["movement_remaining_ft"]
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_counterstrike_player_is_asked_on_own_turn(tmp_path, selection):
    verify_table(tmp_path, "own", selection, "USE")


def test_ai_owned_counterstrike_is_automatic(tmp_path):
    combat, table, mid = F.table_fixture(tmp_path)
    send = F.trigger(combat, table, mid, "ai_enemy")
    combat.set_controller_mode(mid, actor_id=R.ME, controller_mode="LOCAL_AUTO")
    assert send([])["status"] == "COMMITTED"
    loaded = CombatService(R.ROOT, tmp_path)._load_session(mid)
    assert SOVEREIGN_COUNTER_USED in loaded.engine.state.actors[R.ME].turn_flags
    assert len(strikes(loaded.engine.events)) == 1
    assert loaded.mechanical.replay()["status"] == "PASS"
