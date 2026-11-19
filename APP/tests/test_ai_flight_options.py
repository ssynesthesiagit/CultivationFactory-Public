"""Real flyer menus and persisted seat actions; offline providers, no browsers."""
import json
import re

import pytest

from agent_seats.action_options import expand_menu
from agent_seats.choices import build_prompt, decision_payload, turn_options
from agent_seats.protocol import build_prompt as json_prompt
from agent_seats.flight_options import representatives
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate5_service import CombatService
from combat.tabletop import to_battlefield, normalize_map
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_agent_seats import runner_for, raw_state

FLYER, GROUND, AIR = ["actor:factory.aiflight-" + name for name in ("flyer", "ground", "air")]


def flyer_fight(tmp_path, height=0, *, flyer_kit=None):
    """Native Fly Speed, ground/air foes and a finite wall in a real saved table."""
    bundles = []
    for aid in (FLYER, GROUND, AIR):
        doc = sheet(["TAL_AIR_WIND_BORNE_BODY"] if aid == FLYER else [],
                    kit=flyer_kit if aid == FLYER else None)
        doc["identity"]["display_name"] = aid.rsplit('-', 1)[-1].title()
        bundle = compile_character(doc, actor_id=aid)
        if aid != GROUND:
            bundle["actor_template"].update(fly_speed_ft=30, hover=True)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = to_battlefield(normalize_map({"display_name": "Flight yard", "width_squares": 10,
        "height_squares": 8, "walls": [{"shape": "line", "points": [[5, 0], [5, 8]], "height_ft": 10}],
        "starts": {"team1": [[3, 4]], "team2": [[4, 4], [7, 4]]}}))
    mid = combat._finish_factory_match(bundles, [FLYER, GROUND, AIR],
        {FLYER: "team:a", GROUND: "team:b", AIR: "team:b"},
        {FLYER: {"x": 3, "y": 4, "z": height}, GROUND: {"x": 4, "y": 4}, AIR: {"x": 7, "y": 4, "z": 6}},
        arena, [FLYER, GROUND, AIR], [], control_modes={a: "MANUAL" for a in (FLYER, GROUND, AIR)},
        match_seed="AIFLIGHT", display_name="Flight options", maximum_rounds=10)["match_id"]
    runner, _ = runner_for(tmp_path, table)
    while raw_state(runner, mid)["menu"]["actor_id"] != FLYER:
        state = raw_state(runner, mid)
        menu = state["menu"]
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    return combat, table, mid, runner


def menu_frame(combat, mid, runner):
    state = raw_state(runner, mid)
    session = combat._load_session(mid)
    view, known = runner.own_view(mid, state, FLYER, session)
    options = expand_menu(runner._menu(state, known), session.engine, view)
    ranked, scores = [], {}
    builtin, _ = runner._builtin(mid, session, known, options, view["visible_cells"], ranked, scores)
    legal = {k: v["description"] for k, v in options.items()}
    return view, legal, builtin, ranked, scores


@pytest.mark.parametrize("height", [0, 3])
def test_game_ai_scores_vertical_routes_and_can_choose_altitude(tmp_path, height):
    combat, table, mid, runner = flyer_fight(tmp_path, height)
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[FLYER]
    # Remove current attacks to expose the movement decision, without granting
    # new moves. A melee policy must close in three dimensions on the air foe.
    actor.action_available = actor.bonus_action_available = False
    ground = engine.state.actors[GROUND]
    ground.active = ground.action_available = ground.bonus_action_available = False
    ground.current_hp = 0
    engine.state.actors[AIR].position = actor.position.model_copy(update={"z": 6})
    policy, _ = combat.policies.for_actor(FLYER)
    policy = policy.model_copy(update={"preferred_range_bands_ft": ((5, 5),), "position_relative": True})
    context = build_decision_context(engine, policy, for_ai=True)
    pick = LocalDeterministicController().choose_primary_action(context)
    scored = {s.candidate_id for s in pick.record.scored_alternatives}
    assert any(c.candidate_id in scored and c.kind == "MOVE" and c.destination.z != height
               for c in context.legal_candidates)
    assert pick.intent.destination is not None and pick.intent.destination.z > height
    assert engine._distance_actor_to_actor(actor, engine.state.actors[AIR],
                                           actor_position=pick.intent.destination) <= 5
    engine.execute_intent(pick.intent)  # real engine rechecks the proposed move
    assert engine.state.actors[FLYER].position == pick.intent.destination


@pytest.mark.parametrize("profile,kind,model", [
    ("full", "local", "qwen9b"), ("compact", "local", "qwen9b"),
    ("tiny", "local", "qwen9b"), ("choices", "local", "qwen9b"),
    ("choices", "cli", "luna"), ("full", "cli", "sol"),
    ("compact", "cli", "sol-prime"), ("tiny", "cli", "haiku-prime")])
def test_model_seat_flight_survives_profiles_and_table_reload(tmp_path, profile, kind, model):
    combat, table, mid, runner = flyer_fight(tmp_path)
    view, legal, builtin, ranked, scores = menu_frame(combat, mid, runner)
    vertical = representatives(view, legal, ranked)
    assert vertical and any(legal[k]["destination"].get("z") for k in vertical)
    path = runner.registry.path
    provider = {"id": "fake", "kind": kind, "model": model, "timeout_s": 10,
                "prompt_profile": profile, "choices_bytes": 4800, "max_options": 12}
    if kind == "cli":
        provider["command"] = ["offline-test-cli"]
    else:
        provider["base_url"] = "http://127.0.0.1:1/v1"
    path.write_text(json.dumps({"providers": [provider]}))
    seen = []
    def choose(_provider, prompt, png):
        assert png is None
        if profile == "choices":
            lines = [match.groups() for match in re.finditer(r"^([A-L])\) (.+)$", prompt, re.M)]
            letter, selected = next((letter, k) for letter, label in lines for k, row in legal.items()
                                    if row.get("movement_mode") == "fly" and row["destination"].get("z")
                                    and row["movement_label"] in label)
            reply = letter
        else:
            frame = json.loads(prompt.split("\n", 1)[1])
            selected = next(k for k, row in frame["legal_menu"].items()
                            if row.get("movement_mode") == "fly" and row["destination"].get("z"))
            end = next(k for k, row in legal.items() if row["action"] == "End turn")
            reply = json.dumps({"plan": [selected, end]})
        seen.append(legal[selected]["destination"])
        assert "Fly up" in prompt
        return reply, None
    runner.provider = choose
    runner.set_seat(mid, FLYER, "MODEL", "fake")
    assert runner.drive(mid, max_steps=1) == 1
    assert seen
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[FLYER].position == Position.model_validate(seen[0])
    assert runner.decisions(mid)[0].get("fallback") is None


@pytest.mark.parametrize("budget", [800, 1200, 4800])
@pytest.mark.parametrize("height", [0, 3])
def test_d1_payload_keeps_flight_altitude_and_landing(tmp_path, budget, height):
    combat, table, mid, runner = flyer_fight(tmp_path, height)
    view, legal, builtin, ranked, scores = menu_frame(combat, mid, runner)
    options = turn_options(view, legal, builtin, ranked, scores, 3, budget, 12)
    prompt, offered = build_prompt(view, options, "TURN", legal, choices_bytes=budget, max_options=12)
    payload = decision_payload(prompt)
    assert set(payload["options"]) == set(offered)
    assert len(prompt.encode()) <= budget
    assert any("Fly up" in text or "Land" in text or "Fly down" in text for text in payload["options"].values())
    assert "30 ft above ground" in payload["state"]  # perceived airborne foe
    if height:
        assert "15 ft above ground" in payload["state"]
    if budget == 4800 and height:
        assert any("Land" in text for text in payload["options"].values())
    if budget == 4800:
        assert any((legal[k].get("destination") or {}).get("x", 0) > 5 and legal[k].get("movement_mode") == "fly"
                   for answer in offered.values() for k in answer["plan"])


def test_perceived_wall_height_and_attacks_from_altitude(tmp_path):
    combat, table, mid, runner = flyer_fight(tmp_path, 3)
    view, legal, builtin, ranked, scores = menu_frame(combat, mid, runner)
    assert any(AIR in row.get("targets", []) and row.get("economy") in {"ACTION", "Action"}
               for row in legal.values())
    from agent_seats.tactics import observed_grid
    grid = observed_grid(view)
    assert grid.line_of_sight(Position(x=3, y=4, z=3), Position(x=7, y=4, z=6))
    assert not grid.line_of_sight(Position(x=3, y=4), Position(x=7, y=4))


def test_d1_http_seat_commits_offered_flight_and_reloads(tmp_path, monkeypatch):
    from agent_seats.providers import complete
    import urllib.request
    combat, table, mid, runner = flyer_fight(tmp_path)
    view, legal, builtin, ranked, scores = menu_frame(combat, mid, runner)
    runner.registry.path.write_text(json.dumps({"providers": [{"id": "fake", "kind": "d1",
        "base_url": "http://127.0.0.1:1", "choices_bytes": 800, "max_options": 12, "timeout_s": 10}]}))
    selected = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def read(self, _limit):
            return self.body
    def decide(request, timeout):
        payload = json.loads(request.data)
        letter, key = next((letter, k) for letter, label in payload["options"].items() for k, row in legal.items()
                           if row.get("movement_mode") == "fly" and row["destination"].get("z")
                           and row["movement_label"] in label)
        selected.append(legal[key]["destination"])
        response = Response()
        response.body = json.dumps({"choice": letter, "confidence": 1,
            "probabilities": {k: int(k == letter) for k in payload["options"]}, "ms": 0}).encode()
        return response
    monkeypatch.setattr(urllib.request, "urlopen", decide)
    runner.provider = complete
    runner.set_seat(mid, FLYER, "MODEL", "fake")
    assert runner.drive(mid, max_steps=1) == 1
    assert selected
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[FLYER].position == Position.model_validate(selected[0])
    assert runner.decisions(mid)[0]["fallback"] is None


def test_ranged_game_ai_values_flight_out_of_melee_reach(tmp_path):
    from tests.test_p20261010_04_height_ai import BOW_KIT
    combat, table, mid, runner = flyer_fight(tmp_path, flyer_kit=BOW_KIT)
    engine = combat._load_session(mid).engine
    policy, _ = combat.policies.for_actor(FLYER)
    policy = policy.model_copy(update={"preferred_range_bands_ft": ((10, 30),), "position_relative": False})
    context = build_decision_context(engine, policy, for_ai=True)
    up = next(c for c in context.legal_candidates if c.kind == "MOVE"
              and c.metadata.get("movement_mode") == "fly" and c.destination.z > 0
              and c.metadata["flight_tactics"]["destination"]["evaluated"]
              and c.metadata["flight_tactics"]["destination"]["safe_attack"])
    controller = LocalDeterministicController()
    position_score = lambda c: next(part.value for part in controller._score_candidate(context, c, ()).components
                                   if part.component == "flight_position")
    # Check the native safety component with an actual ranged weapon. A
    # point-only altitude threshold is not the engine's full-volume geometry.
    facts = up.metadata["flight_tactics"]["destination"]
    assert GROUND not in facts["melee_threat_ids"] and facts["safe_attack"]
    assert GROUND in up.metadata["flight_tactics"]["current"]["melee_threat_ids"]
    assert position_score(up) > 0
