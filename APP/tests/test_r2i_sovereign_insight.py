"""Sovereign's Opening reveal through compiled actions and table commit/reload."""
import importlib

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

R = importlib.import_module("tests.test_riders_lane2")
I = importlib.import_module("tests.test_r2i_reconcile")
SOVEREIGN = "TAL_IRON_FIST_SOVEREIGN_IRON_BODY_INCARNATION"
NAME = "Sovereign Iron-Body Incarnation"


def reveals(events):
    return [event for event in events if event.event_type == "PASSIVE_TRIGGERED"
            and (event.payload or {}).get("text", "").startswith(NAME + " after ")]


@pytest.mark.parametrize("saves,expected", [
    ({"STR": -3, "DEX": 2, "CON": 1}, "Strength."),
    ({"STR": 3, "DEX": -2, "CON": -2}, "Dexterity, Constitution (tied)."),
    ({"STR": 0, "DEX": 0, "CON": 0}, "Strength, Dexterity, Constitution (tied)."),
])
def test_sovereign_reveals_actual_weakest_saves_on_each_opening(saves, expected):
    engine = R._duel([SOVEREIGN], cl=15)
    R.A._use(engine, NAME, None)
    engine.state.actors[R.FOE].saving_throws = saves
    R.A._ready(engine)
    first = reveals(R._strike(engine))
    assert len(first) == 1 and first[0].payload["text"].endswith(expected)
    assert R.STRIKE in first[0].payload["text"]
    assert engine.state.actors[R.FOE].display_name in first[0].payload["text"]
    assert first[0].actor_id == R.ME and first[0].target_ids == (R.FOE,)
    # Refreshing one's Opening still teaches; there is no printed use limit.
    engine.state.actors[R.FOE].saving_throws = {"STR": 2, "DEX": 1, "CON": -4}
    R.A._ready(engine)
    second = reveals(R._strike(engine))
    assert len(second) == 1 and second[0].payload["text"].endswith("Constitution.")


@pytest.mark.parametrize("case", ["inactive", "unowned", "old_bundle", "miss", "expired", "incapacitated", "other_caster"])
def test_sovereign_insight_is_inert_without_its_owned_active_trigger(case):
    engine = R._duel([] if case == "unowned" else [SOVEREIGN], cl=15)
    if case not in ("unowned", "inactive"):
        R.A._use(engine, NAME, None)
    if case == "old_bundle":
        for action in engine.action_catalog.values():
            action.parameters.get("iron_riders", {}).pop("sovereign_insight", None)
    elif case == "miss":
        engine.state.actors[R.FOE].armor_class = 1000
    elif case == "expired":
        from combat.ext.effect_durations import sweep
        engine.state.round_number += 10
        sweep(engine, engine.state.actors[R.ME], "START_OF_TURN")
    elif case == "incapacitated":
        R._incapacitate(engine)
        engine._remove_condition(engine.state.actors[R.ME], "condition:incapacitated", "test:recover")
    elif case == "other_caster":
        marker = next(c for c in engine.state.actors[R.ME].conditions.values()
                      if c.condition_id == "condition:typed.sovereign_iron_body")
        marker.source_actor_id = R.FOE
    R.A._ready(engine)
    assert not reveals(R._strike(engine))


def test_sovereign_reveals_after_non_damaging_unarmed_grapple_opening():
    engine = R._duel([SOVEREIGN], cl=15, dc=50)
    R.A._use(engine, NAME, None)
    engine.state.actors[R.FOE].saving_throws = {"STR": -100, "DEX": -90, "CON": 0}
    R.A._ready(engine)
    events = R._strike(engine, "Grapple")
    assert not any(e.event_type == "DAMAGE_COMMITTED" for e in events)
    assert len(reveals(events)) == 1
    assert "Grapple" in reveals(events)[0].payload["text"]
    assert reveals(events)[0].payload["text"].endswith("Strength.")


def table_fixture(tmp_path, *, authority=None):
    bundles = []
    for aid in (R.ME, R.FOE):
        owned = [SOVEREIGN, "TAL_IRON_FIST_COUNTER_PALM", "tianxia.talent.pressure_points.patient_hand"] if aid == R.ME else []
        bundle = compile_character(R.A._sheet(R.IRON_FIST if owned else None, owned, R.KIT, cl=15),
                                   actor_id=aid, reaction_plan={"ask": True} if owned else None,
                                   typed_authority=authority)
        bundle["actor_template"].update(armor_class=1000 if owned else 0, maximum_hp=400,
                                        speed_ft=0, initiative_bonus=100 if owned else -100)
        bundle["actor_template"]["saving_throws"] = {"STR": 5, "DEX": -1, "CON": -1}
        for action in bundle["action_catalog"]:
            if action["parameters"].get("typed"):
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(R.ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="R2I-SOVEREIGN", typed_bundles=bundles,
        roster_setup={"primary_actor_ids": [R.ME, R.FOE], "team_by_actor": {R.ME: "team:a", R.FOE: "team:b"},
                      "starting_positions": {R.ME: {"x": 3, "y": 6}, R.FOE: {"x": 4, "y": 6}}})
    table = TabletopService(combat, tmp_path)
    assert I.act(combat, table, session.match_id, NAME)["status"] == "COMMITTED"
    return combat, table, session.match_id


@pytest.mark.parametrize("turn", ["own", "manual_enemy", "ai_enemy"])
def test_sovereign_table_reveal_commits_once_and_replays_after_reload(tmp_path, turn):
    combat, table, mid = table_fixture(tmp_path)
    if turn == "own":
        result = I.act(combat, table, mid, R.STRIKE, R.FOE)
    else:
        assert I.act(combat, table, mid, "Dodge")["status"] == "COMMITTED"
        assert I.act(combat, table, mid, "END")["status"] == "COMMITTED"
        menu = table.state(mid)["menu"]
        candidate = next(c for c in combat.decision(mid)["context"]["legal_candidates"]
                         if c["display_name"] == "Fu (Short Axe) attack" and R.ME in c["target_ids"])
        if turn == "ai_enemy":
            real = combat.controller

            class AttackController:
                def choose_primary_action(self, context):
                    return ManualControllerAdapter(lambda _: (candidate["candidate_id"], ())).choose_primary_action(context)

                def __getattr__(self, name):
                    return getattr(real, name)

            combat.controller = AttackController()
            combat.set_controller_mode(mid, actor_id=R.FOE, controller_mode="LOCAL_AUTO")

        def send(answers):
            return table.auto_step(mid, 0, answers) if turn == "ai_enemy" else table.act(
                mid, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, answers)

        before = combat._load_session(mid).engine.state.model_dump(mode="json")
        result = send([])
        assert result["status"] == "REACTION_REQUIRED"
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        assert not reveals(combat._load_session(mid).engine.events)
        prompt = result["reaction"]
        assert prompt["context"]["reactor_id"] == R.ME
        answers = [{**prompt["context"], "selection": "USE"}]
        result = send(answers)
        assert result["status"] == "REACTION_REQUIRED"
        counter = result["reaction"]
        assert counter["context"]["reaction_source_id"] == "choice:needle.sovereign_counterstrike"
        assert counter["choice"]["allow_decline"]
        result = send([*answers, {**counter["context"], "selection": "DECLINE", "option_ids": []}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(R.ROOT, tmp_path)._load_session(mid)
    notes = reveals(loaded.engine.events)
    assert len(notes) == 1
    assert notes[0].payload["text"].endswith("Dexterity, Constitution (tied).")
    assert (R.STRIKE if turn == "own" else "Counter Palm") in notes[0].payload["text"]
    assert notes[0].target_ids == (R.FOE,)
    assert loaded.engine.state.model_dump(mode="json") == combat._load_session(mid).engine.state.model_dump(mode="json")
    assert loaded.mechanical.replay()["status"] == "PASS"
