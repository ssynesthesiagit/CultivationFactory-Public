"""Owned Sovereign extra Forms through real hit choices and table reloads."""
import importlib

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.iron_forms import SOVEREIGN_USED, ELBOW
from combat.gate2_runtime_models import ReactionDecision

R = importlib.import_module("tests.test_riders_lane2")
I = importlib.import_module("tests.test_r2i_reconcile")
S = importlib.import_module("tests.test_r2i_sovereign_insight")
NAME, SOURCE = S.NAME, S.SOVEREIGN


def engine_fixture(case="active", *, decline=False):
    talents = ["TAL_IRON_FIST_COUNTER_PALM", R.BREAKING]
    if case != "unowned":
        talents.append(SOURCE)
    engine = R._duel(talents, cl=15)
    if case not in ("inactive", "unowned"):
        R.A._use(engine, NAME, None)
    if case == "old_bundle":
        for action in engine.action_catalog.values():
            action.parameters.get("iron_riders", {}).pop("sovereign_forms", None)
    elif case == "expired":
        from combat.ext.effect_durations import sweep
        engine.state.round_number += 10
        sweep(engine, engine.state.actors[R.ME], "START_OF_TURN")
    elif case == "incapacitated":
        R._incapacitate(engine)
        engine._remove_condition(engine.state.actors[R.ME], "condition:incapacitated", "test:recover")
    elif case == "other_caster":
        next(c for c in engine.state.actors[R.ME].conditions.values()
             if c.condition_id == "condition:typed.sovereign_iron_body").source_actor_id = R.FOE
    R._foe_turn(engine)
    engine.state.actors[R.ME].armor_class = 1000
    engine.state.actors[R.FOE].armor_class = 1000 if case == "miss" else -50
    engine.state.actors[R.ME].resources["resource:core.martial_focus"] = 1
    if case == "immune":
        engine._add_modifier(engine.state.actors[R.FOE], "test:immune", "damage_immunity", "ADD", "BLUDGEONING", "SELF", expires_on="UNTIL_REMOVED")
    requests = []

    def provider(req):
        requests.append(req)
        text = (req.get("choice_trigger") or {}).get("prompt", "")
        extra = NAME in text and "choose one extra Form" in text
        skip = req.get("extension_choice") and (not extra or decline)
        return ReactionDecision(checkpoint=req["checkpoint"], reactor_id=req["reactor_id"],
                                reaction_source_id=req["reaction_source_id"],
                                selection="DECLINE" if skip else "USE",
                                option_ids=(R.BREAKING,) if extra and not decline else ()), None

    engine._gate4_reaction_provider = provider
    return engine, requests


def extra_requests(requests):
    return [req for req in requests if NAME in (req.get("choice_trigger") or {}).get("prompt", "")
            and "choose one extra Form" in (req.get("choice_trigger") or {}).get("prompt", "")]


def test_sovereign_extra_form_once_each_actual_turn_and_decline_is_free():
    engine, requests = engine_fixture()
    R._foe_attacks(engine)
    assert len(extra_requests(requests)) == 1
    stamp = engine.state.actors[R.ME].turn_flags[SOVEREIGN_USED]
    assert isinstance(stamp, str) and f":{R.FOE}:" in stamp
    for new_turn in (False, True):
        engine.state.actors[R.FOE].action_available = True
        engine.state.actors[R.ME].reaction_available = True
        engine.state.actors[R.ME].resources["resource:core.martial_focus"] = 1
        if new_turn:
            engine.state.actors[R.FOE].turns_started += 1
        R._foe_attacks(engine)
        assert len(extra_requests(requests)) == (2 if new_turn else 1)
    declined, requests = engine_fixture(decline=True)
    R._foe_attacks(declined)
    assert len(extra_requests(requests)) == 1
    assert SOVEREIGN_USED not in declined.state.actors[R.ME].turn_flags


def test_sovereign_does_not_duplicate_a_form_scheduled_on_an_ordinary_strike():
    engine = R._duel([SOURCE, R.BREAKING], cl=15)
    R.A._use(engine, NAME, None)
    requests = R._answer_options(engine, lambda req: req.get("legal_option_ids", [])[:1])
    R.A._ready(engine)
    R._strike(engine)
    assert not extra_requests(requests)
    assert SOVEREIGN_USED not in engine.state.actors[R.ME].turn_flags


def test_sovereign_court_and_counter_palm_apply_three_distinct_forms():
    from combat.ext.iron_forms import RISING, COURT_USED
    engine = R._duel([SOURCE, R.COURT, R.BREAKING, RISING, ELBOW, "TAL_IRON_FIST_COUNTER_PALM"], cl=15)
    R.A._use(engine, NAME, None)
    R.A._ready(engine)
    engine.state.actors[R.ME].resources["resource:core.martial_focus"] = 1
    R.A._use(engine, "Court of One Hundred Forms", None)
    R._open(engine)
    engine._apply_condition(engine.state.actors[R.FOE], "condition:typed.grappled", "test:grapple", R.ME,
                            expires_on="UNTIL_REMOVED")
    R._foe_turn(engine)
    engine.state.actors[R.ME].armor_class = 1000
    engine.state.actors[R.ME].resources["resource:core.martial_focus"] = 1
    requests = R._answer_options(engine, lambda req: req.get("legal_option_ids", [])[:1])
    R._foe_attacks(engine)
    counter_index = next(i for i, req in enumerate(requests)
                         if req["reaction_source_id"] == "choice:needle.sovereign_counterstrike")
    forms = [req for req in requests[:counter_index] if req["reaction_source_id"] == "choice:needle.iron_forms"]
    assert len(forms) == 3
    assert {req["legal_option_ids"][0] for req in forms} == {R.BREAKING, RISING, ELBOW}
    assert len(extra_requests(requests)) == 1
    assert SOVEREIGN_USED in engine.state.actors[R.ME].turn_flags
    assert COURT_USED in engine.state.actors[R.ME].turn_flags


@pytest.mark.parametrize("case", ["inactive", "unowned", "old_bundle", "expired", "incapacitated", "other_caster", "miss", "immune"])
def test_sovereign_form_gates(case):
    engine, requests = engine_fixture(case)
    R._foe_attacks(engine)
    assert not extra_requests(requests)
    assert SOVEREIGN_USED not in engine.state.actors[R.ME].turn_flags


def table_fixture(tmp_path, *, authority=None, foe_counter=False):
    bundles = []
    for aid in (R.ME, R.FOE):
        talents = [SOURCE, R.BREAKING, ELBOW, "TAL_IRON_FIST_COUNTER_PALM",
                   "TAL_IRON_FIST_SKY_SHATTERING_AXE_KICK",
                   "tianxia.talent.pressure_points.patient_hand"] if aid == R.ME else (["TAL_IRON_FIST_COUNTER_PALM"] if foe_counter else [])
        bundle = compile_character(R.A._sheet(R.IRON_FIST if talents else None, talents, R.KIT, cl=15),
                                   actor_id=aid, reaction_plan={"ask": True} if talents else None,
                                   typed_authority=authority)
        bundle["actor_template"].update(armor_class=1000 if talents else 0, maximum_hp=1000,
                                        speed_ft=0, initiative_bonus=100 if aid == R.ME else -100)
        for action in bundle["action_catalog"]:
            if action["parameters"].get("typed"):
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(R.ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="R2I-SOVEREIGN-OWN" if foe_counter else "R2I-SOVEREIGN-FORMS", typed_bundles=bundles,
        roster_setup={"primary_actor_ids": [R.ME, R.FOE], "team_by_actor": {R.ME: "team:a", R.FOE: "team:b"},
                      "starting_positions": {R.ME: {"x": 3, "y": 6}, R.FOE: {"x": 4, "y": 6}}})
    table = TabletopService(combat, tmp_path)
    assert I.act(combat, table, session.match_id, NAME)["status"] == "COMMITTED"
    return combat, table, session.match_id


def trigger(combat, table, mid, turn):
    # Patient Hand restores Focus through a real Dodge after Sovereign spent it.
    assert I.act(combat, table, mid, "Dodge")["status"] == "COMMITTED"
    assert I.act(combat, table, mid, "END")["status"] == "COMMITTED"
    if turn == "own":
        assert I.act(combat, table, mid, "Dodge")["status"] == "COMMITTED"
        assert I.act(combat, table, mid, "END")["status"] == "COMMITTED"
    menu = table.state(mid)["menu"]
    name, target = ("Sky-Shattering Axe Kick", R.FOE) if turn == "own" else ("Fu (Short Axe) attack", R.ME)
    candidate = next(c for c in combat.decision(mid)["context"]["legal_candidates"]
                     if c["display_name"] == name and target in c["target_ids"])
    if turn == "ai_enemy":
        real = combat.controller

        class AttackController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (candidate["candidate_id"], ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = AttackController()
        combat.set_controller_mode(mid, actor_id=R.FOE, controller_mode="LOCAL_AUTO")
    return lambda answers: table.auto_step(mid, 0, answers) if turn == "ai_enemy" else table.act(
        mid, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, answers)


@pytest.mark.parametrize("turn", ["own", "manual_enemy", "ai_enemy"])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_sovereign_table_extra_form_asks_rolls_back_commits_and_reloads(tmp_path, turn, selection):
    combat, table, mid = table_fixture(tmp_path)
    send = trigger(combat, table, mid, turn)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answers, extra = [], []
    for _ in range(8):
        result = send(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            if NAME in prompt["moment"] and "choose one extra Form" in prompt["moment"]:
                extra.append(prompt)
                assert prompt["context"]["reactor_id"] == R.ME
                assert ("Sky-Shattering Axe Kick" if turn == "own" else "Counter Palm") in prompt["moment"]
                assert combat._load_session(mid).engine.state.actors[R.FOE].display_name in prompt["moment"]
                assert prompt["choice"]["allow_decline"]
                options = [o["id"] for o in prompt["choice"]["options"]]
                assert R.BREAKING in options
                answer.update(selection=selection, option_ids=[options[0]] if selection == "USE" else [])
            elif prompt["context"]["reaction_source_id"] == "choice:needle.iron_forms":
                # Decline Counter Palm's ordinary Form, leaving it eligible for Sovereign.
                answer.update(selection="DECLINE", option_ids=[])
            elif prompt["context"]["reaction_source_id"] == "choice:needle.sovereign_counterstrike":
                answer.update(selection="DECLINE", option_ids=[])
            else:
                answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
        answers.append(answer)
    assert result["status"] == "COMMITTED" and len(extra) == 1
    loaded = CombatService(R.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.model_dump(mode="json") == combat._load_session(mid).engine.state.model_dump(mode="json")
    assert (SOVEREIGN_USED in loaded.engine.state.actors[R.ME].turn_flags) == (selection == "USE")
    assert loaded.engine.state.actors[R.ME].movement_remaining_ft == before["actors"][R.ME]["movement_remaining_ft"]
    assert loaded.engine.state.actors[R.FOE].movement_remaining_ft == before["actors"][R.FOE]["movement_remaining_ft"]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_sovereign_ai_owner_chooses_automatically_on_ai_turn(tmp_path):
    combat, table, mid = table_fixture(tmp_path)
    send = trigger(combat, table, mid, "ai_enemy")
    combat.set_controller_mode(mid, actor_id=R.ME, controller_mode="LOCAL_AUTO")
    assert send([])["status"] == "COMMITTED"
    loaded = CombatService(R.ROOT, tmp_path)._load_session(mid)
    assert SOVEREIGN_USED in loaded.engine.state.actors[R.ME].turn_flags
    assert loaded.mechanical.replay()["status"] == "PASS"
