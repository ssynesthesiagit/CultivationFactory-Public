"""Public synthetic regressions for the Gōruden review and main integration."""
from types import SimpleNamespace

import pytest

from combat import ext, zones
from combat.ext import goruden, goruden_journey
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet
from tests.test_mgr_t14_goruden import game, prepare, use
from tests.worker2_support import OWNER, FOE, reload, turn


@pytest.mark.parametrize("packet,eligible", [(200, True), (240, False), (500, False)])
def test_statue_fixture_damage_distinguishes_lethal_from_outright(tmp_path, packet, eligible):
    from tests.cw2_service_support import add_action, seal
    from tests.worker2_support import fixture

    def setup(bundles):
        prepare(bundles)
        bundles[0]["actor_template"]["maximum_hp"] = 120
        seal(bundles[0])
        add_action(bundles[2], "Lethal boundary trial", [
            {"type": "damage", "flat": packet, "damage_types": ["force"], "applies_to": "target"}])

    c, table, mid = fixture(tmp_path, [], cl=18, primary="Stamina",
        owner_path="Body Refining", owner_features=[goruden.PREFIX + n for n in
        ("golden_sheen", "gilded_bones", "radiant_fist", "golden_aura", "immortal_gold")],
        bundle_transform=setup, owner_pb=6)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER]
    assert before.maximum_hp == before.current_hp == 120
    prompts = use(c, table, mid, "Lethal boundary trial", OWNER,
                  {"choice:needle.goruden.immortal_gold": ["survive"]})
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert any(p["context"]["reaction_source_id"] == "choice:needle.goruden.immortal_gold"
               for p in prompts) is eligible
    assert any(c.condition_id == goruden.STATUE for c in actor.conditions.values()) is eligible
    assert actor.resources["resource:core.stamina"] == before.resources["resource:core.stamina"] - (6 if eligible else 0)
    if eligible:
        assert actor.current_hp == 1
        turn(table, mid, OWNER)
        actor = reload(tmp_path, mid).state.actors[OWNER]
        assert actor.current_hp == 31 and actor.action_available


def test_aura_missing_owner_is_inert(tmp_path):
    c, table, mid = game(tmp_path)
    use(c, table, mid, "Golden Aura")
    engine = reload(tmp_path, mid)
    zone = next(z for z in zones.typed_zones(engine) if z.owner_id == OWNER)
    orphan = zone.model_copy(update={"owner_id": "actor:absent"})
    before = engine.state.model_dump_json()
    goruden._ask_aura(engine, orphan, engine.state.actors[FOE], None)
    assert engine.state.model_dump_json() == before


@pytest.mark.parametrize("radius_cells,subject_x,expected", [(3, 7, True), (1, 5, False)])
def test_moving_aura_uses_stored_geometry_not_ten_foot_literal(
        tmp_path, monkeypatch, radius_cells, subject_x, expected):
    c, table, mid = game(tmp_path)
    use(c, table, mid, "Golden Aura")
    engine = reload(tmp_path, mid)
    zone = next(z for z in zones.typed_zones(engine) if z.owner_id == OWNER)
    zone.radius_cells = radius_cells
    zone.trigger_profile['size_ft'] = radius_cells * engine.grid.square_size_ft
    subject = engine.state.actors[FOE]
    subject.position = Position(x=subject_x, y=6)
    seen = []
    monkeypatch.setattr(goruden, "_ask_aura", lambda e, z, s, i: seen.append(s.entity_id))
    goruden.golden_aura_arrival(engine, engine.state.actors[OWNER],
                               Position(x=3, y=6), Position(x=4, y=6), False)
    assert (FOE in seen) is expected
    zone.active = False
    seen.clear()
    goruden.golden_aura_arrival(engine, engine.state.actors[OWNER],
                               Position(x=3, y=6), Position(x=4, y=6), False)
    assert not seen  # typed_zones excludes inactive stored zones.


@pytest.mark.parametrize("current,expected", [(0, 1), (10, 0)])
def test_short_recovery_automatic_choice_is_explicit(current, expected):
    actor = {"resources": {goruden_journey.STAMINA: current}, "source_states": {
        goruden_journey.FAMILY: {"short_recovery_choice": {"amount": 5}}},
        "bundle": {"typed_passives": [{"feature_id": goruden.PREFIX + "golden_sheen"}],
                   "action_catalog": [], "actor_template": {"resources": [
                       {"resource_id": goruden_journey.STAMINA, "maximum": 10}]}}}
    rows = goruden_journey.native_body_options(
        SimpleNamespace(state={"phase": "travel", "actors": {"a": actor}}), "a")
    assert {row["payload"]["recover"] for row in rows} == {0, 1}
    assert [row["payload"]["recover"] for row in rows if row["auto_select"]] == [expected]


def test_single_native_journal_replays_world_scene_and_persists_source_state(tmp_path, monkeypatch):
    from combat.fact_consent_admission import read

    source = "test:review-f16"
    def schema(session, row_source, subject, kind):
        if row_source == source and kind == "ambient":
            return {"authority": "table_owner", "value_type": "flag",
                    "maximum_seconds": 60, "description": "Test ambient condition"}

    monkeypatch.setitem(ext._HOOKS, "fact_admission_schema",
                        [*ext._HOOKS["fact_admission_schema"], schema])
    actor = "actor:test.traveler"
    bundle = compile_character(sheet([], cl=18), actor_id=actor)
    arena = {"stable_id": "battlefield:review", "display_name": "Review courtyard",
             "width_squares": 8, "height_squares": 8, "square_size_ft": 5,
             "terrain_regions": [], "starting_positions": {}}
    def cold():
        return CombatService(ROOT, tmp_path)
    state = cold().journeys.create([bundle], arena, {actor: {"x": 2, "y": 2}}, {actor: 30})
    jid = state["journey_id"]
    state = cold().journey_world_fact(jid, state["revision"], {
        "source": source, "subject": actor, "kind": "ambient", "scope": "training",
        "value": 1, "expires_at": 60, "readers": [actor]})
    assert read(cold().journeys.load(jid), source, actor, "ambient", "training", actor)["value"] == 1
    state = cold().journey_end_scene(jid, state["revision"], "The training bout ends.")
    state = cold().journey_act(jid, state["revision"], actor, "wait", {"seconds": 6})
    assert cold().journey_verify(jid)["commands"] == 3
    assert cold().journey_replay(jid)["status"] == "PASS"
    # A source's durable state must survive closing and admitting a new journey.
    session = cold().journeys.load(jid)
    session.state["actors"][actor]["source_states"] = {"test:source": {"uses": 1}}
    cold().journeys.save(session)
    state = cold().journey_act(jid, state["revision"], actor, "finish", {})
    assert cold().journey_verify(jid)["status"] == "PASS"
    state = cold().journeys.create([bundle], arena, {actor: {"x": 2, "y": 2}}, {actor: 30})
    assert state["actors"][actor]["source_states"] == {"test:source": {"uses": 1}}
    assert "command_replay" not in state  # no second replay implementation.


@pytest.mark.parametrize("invalid,message", [
    ("creature", "choose a creature"), ("source", "missing its ability"),
    ("answers", "answers are unavailable"), ("readers", "share the answer")])
def test_fact_question_errors_are_plain_player_instructions(invalid, message):
    from combat.fact_consent_admission import admit_choice
    subject = SimpleNamespace(entity_id="actor:test")
    ctx = SimpleNamespace(engine=SimpleNamespace(state=SimpleNamespace(
        actors={subject.entity_id: subject})), intent=object())
    if invalid == "creature":
        ctx.intent = None
    with pytest.raises(ValueError, match=message):
        admit_choice(ctx, subject, "" if invalid == "source" else "test:source",
            "consent", "offer", [] if invalid == "answers" else ["accept"],
            labels={"accept": "Accept"}, prompt="Accept this offer?",
            expires_on="END_OF_TURN", readers=("actor:absent",) if invalid == "readers" else ())


@pytest.mark.parametrize("immune", [False, True])
def test_damage_receipt_precedes_distinct_nonimmune_response(monkeypatch, immune):
    from combat.typed_reactions import _defenses, defend
    from tests.test_typed_executor import _reactor

    engine, attacker, target = _reactor("REVIEW-RECEIPT", [])
    if immune:
        engine.typed_passive_rows[target.entity_id] = [
            {"block": "defense", "kind": "immunity", "damage_types": ["FIRE"],
             "feature_id": "test:immunity"}]
    calls = []
    def receipt(*args):
        calls.append("receipt")
    def response(*args):
        calls.append("response")
        return [{"kind": "resistance", "damage_types": ["FIRE"]}]
    monkeypatch.setitem(ext._HOOKS, "damage_defense_receipt", [receipt])
    monkeypatch.setitem(ext._HOOKS, "before_damage_defenses", [response])
    _defenses(engine, target, "FIRE", None, None)
    assert not calls  # pure estimates never enter either transactional hook.
    assert defend(engine, target, 20, "FIRE", None, None) == (0 if immune else 10)
    assert calls == (["receipt"] if immune else ["receipt", "response"])
