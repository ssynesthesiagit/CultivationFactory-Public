"""C13 review regressions through native intents, table previews and persistence."""
from types import SimpleNamespace

import pytest

from tests import test_riders_c13 as C
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate5_service import CombatService, _ReactionRequired
from combat.tabletop_service import TabletopService


def intent(engine, name, actor=None, destination=None):
    c = next(c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name
             and (actor is None or c.actor_id == actor)
             and (destination is None or c.destination == destination))
    return ActionIntent(intent_id=f"review-{engine.state.event_sequence}", decision_id=c.decision_id,
                        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
                        target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids)


def accept(request, options=()):
    return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                            reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=tuple(options)), None


@pytest.mark.parametrize("dc", [-40, 50])
def test_reeling_immunity_ends_before_ordinary_movement_and_dash(dc):
    engine, me, foe = C._fight(C.DRUNKEN, dc=dc)
    budget = me.movement_remaining_ft
    requests = []

    def provider(request):
        requests.append(request)
        options = request.get("legal_option_ids") or ()
        if str(request["reaction_source_id"]).endswith("drunken_reeling_move"):
            return accept(request, ["cell:2,6"])
        return accept(request, options[:1])

    engine.set_reaction_provider(provider)
    C._use(engine, "Reeling Step", target=None)
    assert (me.position.x, me.position.y) == (2, 6)
    assert me.movement_remaining_ft == budget
    assert foe.reaction_available
    assert not any("OPPORTUNITY" in r["checkpoint"] for r in requests)
    C._move(engine, C.ME, (3, 6))
    C._move(engine, C.ME, (2, 6))
    assert not foe.reaction_available  # ordinary movement provokes immediately
    foe.reaction_available = True
    C._use(engine, "Dash", target=None)
    C._move(engine, C.ME, (3, 6))
    C._move(engine, C.ME, (2, 6))
    assert not foe.reaction_available  # Dash does not inherit immunity either
    assert not getattr(engine, "_granted_movement_oa", None)


def swaying_engine():
    from combat.factory_compiler import compile_character
    bundle = C._bundle(C.DRUNKEN, items=C.AXE_ITEMS, features=C.EXTRA)
    foe = compile_character(C._sheet("tianxia.sphere.athletics", items=C.AXE_ITEMS), actor_id=C.FOE)
    engine = C.t.Gate4ControllerEngine(C.ROOT, match_seed="C13-REVIEW-SWAY", typed_bundles=(bundle, foe),
        roster_setup={"primary_actor_ids": [C.ME, C.FOE], "team_by_actor": {C.ME: "team:a", C.FOE: "team:b"},
                      "starting_positions": {C.ME: {"x": 3, "y": 6}, C.FOE: {"x": 4, "y": 6}}})
    me, attacker = engine.state.actors[C.ME], engine.state.actors[C.FOE]
    from combat.ext.drunken_style import _mark
    _mark(engine, me, attacker, next(a for a in me.action_ids if a.endswith("broken_rhythm")))
    engine.state.current_actor_id = C.FOE
    engine.state.current_slot_index = engine.state.initiative_order.index(C.FOE)
    engine._system_start_turn()
    engine.typed_ask_reactors = frozenset({C.ME})
    return engine, me, attacker


@pytest.mark.parametrize("first_hit", [True, False])
def test_swaying_record_consumed_for_triggering_attack(first_hit):
    from combat.ext.drunken_style import SWAY_FLAG
    engine, me, attacker = swaying_engine()
    requests = []
    def provider(request):
        requests.append(request)
        options = request.get("legal_option_ids") or ()
        if str(request["reaction_source_id"]).endswith("drunken_swaying_step"):
            return accept(request, ["cell:3,5"])
        if "SWAYING_GUARD" in request["reaction_source_id"]:
            return accept(request, options[:1])
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
            reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None
    engine.set_reaction_provider(provider)
    me.armor_class = -50 if first_hit else 100
    me.maximum_hp = 1000
    me.current_hp = 1000
    engine.execute_intent(intent(engine, "Fu (Short Axe) attack", C.FOE))
    assert not me.reaction_available
    assert SWAY_FLAG not in me.turn_flags
    steps = [r for r in requests if str(r["reaction_source_id"]).endswith("drunken_swaying_step")]
    assert bool(steps) is (not first_hit)
    if steps:
        assert "misses" in steps[0]["choice_trigger"]["prompt"]
        assert (me.position.x, me.position.y) == (3, 5)
    requests.clear()
    attacker.action_available = True
    me.armor_class = 100
    engine.execute_intent(intent(engine, "Fu (Short Axe) attack", C.FOE))
    # auto/methods 2026-10-04: Swaying Guard's printed sentence adds "You may expend Martial Focus to use Swaying Guard
    # without spending your Reaction. Once you do so, you cannot use Swaying Guard again until the start of your next
    # turn", so the SECOND use in this round is the printed Focus-paid one (it happens because the first use spent the
    # Reaction) and its miss step is legal. The printed limit then blocks any further paid use, so a third attack offers
    # no step at all. Before that sentence was automated this branch asserted the old limitation instead.
    assert me.resources.get("resource:core.martial_focus", 0) == 0, "the printed Martial Focus cost was not paid"
    requests.clear()
    attacker.action_available = True
    engine.execute_intent(intent(engine, "Fu (Short Axe) attack", C.FOE))
    assert not any(str(r["reaction_source_id"]).endswith("drunken_swaying_step") for r in requests)


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_swaying_player_is_asked_on_ai_turn_and_ai_actor_is_automatic(tmp_path, mode):
    engine, me, attacker = swaying_engine()
    engine.typed_ask_reactors = frozenset({C.ME}) if mode == "MANUAL" else frozenset()
    for row in engine.typed_reaction_rows[C.ME]:
        if row.get("feature_id") == "TAL_DRUNKEN_STYLE_SWAYING_GUARD":
            row["ask"] = True
    service = CombatService(C.ROOT, tmp_path)
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    choice = SimpleNamespace(intent=intent(engine, "Fu (Short Axe) attack", C.FOE))
    before = engine.state.model_dump(mode="json")
    needed = service._ask_during_ai_step(session, choice, {})
    if mode == "MANUAL":
        assert needed is not None and needed.context.reactor_id == C.ME
        assert "SWAYING_GUARD" in needed.context.reaction_source_id
    else:
        assert needed is None
    assert engine.state.model_dump(mode="json") == before


def test_reeling_commit_reload_has_no_exemption_or_extra_movement(tmp_path):
    persistence, session = C._persisted(tmp_path, C._bundle(C.DRUNKEN), "C13-REELING-PERSIST")
    engine = session.engine
    budget = engine.state.actors[C.ME].movement_remaining_ft
    def provider(request):
        options = request.get("legal_option_ids") or ()
        return accept(request, ["cell:2,6"] if str(request["reaction_source_id"]).endswith("drunken_reeling_move") else options[:1])
    session.submit_intent(intent(engine, "Reeling Step"), primary_decision_record=None, reaction_provider=provider)
    loaded = persistence.load_match(session.match_id).engine
    me = loaded.state.actors[C.ME]
    assert (me.position.x, me.position.y) == (2, 6)
    assert me.movement_remaining_ft == budget
    assert "drunken_reeling_no_oa" not in me.turn_flags
    assert "spark_step_ignore_oa_from" not in me.turn_flags
    assert not getattr(loaded, "_granted_movement_oa", None)


def test_swaying_table_preview_asks_for_a_step_after_a_miss(tmp_path, monkeypatch):
    engine, me, attacker = swaying_engine()
    me.armor_class = 100
    service = CombatService(C.ROOT, tmp_path)
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    metadata = {"participant_control_modes": {C.ME: "MANUAL", C.FOE: "LOCAL_AUTO"}}
    action = intent(engine, "Fu (Short Axe) attack", C.FOE)
    answers = []
    for _ in range(4):
        try:
            service._run_preview(session, metadata, action, tuple(answers))
        except _ReactionRequired as exc:
            context = exc.context
            if context.reaction_source_id.endswith("drunken_swaying_step"):
                assert context.reactor_id == C.ME
                assert "misses" in context.choice_trigger["prompt"]
                assert context.choice_trigger["target_id"] == C.ME
                table = TabletopService(service, tmp_path)
                monkeypatch.setattr(table, "_names_for", lambda mid: ({a.entity_id: a.display_name for a in engine.state.actors.values()}, {}))
                prompt = table._reaction_prompt(session.match_id, context.model_dump(mode="json"), engine=engine)
                assert "Swaying Guard" in prompt["moment"]
                assert "misses" in prompt["moment"]
                return
            answers.append(ReactionDecision(checkpoint=context.checkpoint, reactor_id=context.reactor_id,
                reaction_source_id=context.reaction_source_id, selection="USE"))
    pytest.fail("manual guarded miss did not ask its owner for the step")


@pytest.mark.parametrize("dc,stopped", [(60, True), (-40, False)])
def test_reeling_preserves_movement_loss_from_an_unexempted_opportunity_attack(dc, stopped):
    from combat.factory_compiler import compile_character
    from combat.canonical import canonical_sha256
    watcher = "actor:review.watcher"
    foe = compile_character(C._sheet("tianxia.sphere.athletics", items=C.AXE_ITEMS), actor_id=C.FOE)
    # A native typed weapon attack carrying a movement-stopping on-hit effect.
    for action in foe["action_catalog"]:
        for effect in (action["parameters"].get("typed") or {}).get("effects") or []:
            if effect["type"] == "attack":
                effect.setdefault("on_hit", []).append({"type": "remaining_movement", "applies_to": "target", "becomes": 0})
    foe["bundle_sha256"] = canonical_sha256({k: v for k, v in foe.items() if k != "bundle_sha256"})
    far = compile_character(C._sheet("tianxia.sphere.athletics", items=C.AXE_ITEMS), actor_id=watcher)
    engine = C.t.Gate4ControllerEngine(C.ROOT, match_seed="C13-MOVEMENT-STOP", typed_bundles=(C._bundle(C.DRUNKEN, dc=dc), foe, far),
        roster_setup={"primary_actor_ids": [C.ME, C.FOE, watcher],
            "team_by_actor": {C.ME: "team:a", C.FOE: "team:b", watcher: "team:b"},
            "starting_positions": {C.ME: {"x": 3, "y": 6}, C.FOE: {"x": 4, "y": 6}, watcher: {"x": 8, "y": 6}}})
    me = engine.state.actors[C.ME]
    me.armor_class = -50
    me.maximum_hp = 1000
    me.current_hp = 1000
    budget = me.movement_remaining_ft
    def provider(request):
        key = str(request["reaction_source_id"])
        options = request.get("legal_option_ids") or ()
        picks = [watcher] if key.endswith("drunken_reeling_oa") else ["cell:2,6"] if key.endswith("drunken_reeling_move") else options[:1]
        return accept(request, picks)
    engine.set_reaction_provider(provider)
    C._use(engine, "Reeling Step", target=None)
    assert engine.state.actors[C.FOE].reaction_available is (not stopped)
    assert me.movement_remaining_ft == (0 if stopped else budget)
    assert (me.position.x, me.position.y) == ((3, 6) if stopped else (2, 6))


def test_reeling_granted_paths_respect_existing_chain_tether_limits():
    engine, me, foe = C._fight(C.DRUNKEN, dc=60)
    engine._apply_condition(me, "condition:typed.bound", "test:tether", foe.entity_id,
                            expires_on="UNTIL_REMOVED", data={"tether_ft": 5})
    def choose(options):
        assert "cell:2,6" not in options  # would exceed the 5-foot tether
        return ["cell:3,5"]
    requests = C._answers(engine, {"drunken_reeling_move": choose})
    C._use(engine, "Reeling Step", target=None)
    assert any(r["reaction_source_id"].endswith("drunken_reeling_move") for r in requests)
    assert (me.position.x, me.position.y) == (3, 5)
    assert engine.grid.distance_ft(me.position, foe.position) <= 5


@pytest.mark.parametrize("hit", [True, False])
def test_swaying_attack_outcome_and_step_survive_commit_reload(tmp_path, hit):
    import copy
    from combat.canonical import canonical_sha256
    from combat.factory_compiler import compile_character
    from combat.gate4_persistence import Gate4Persistence
    from combat.ext.drunken_style import OFF_RHYTHM_ROW, SWAY_FLAG
    me = C._bundle(C.DRUNKEN, items=C.AXE_ITEMS)
    me["actor_template"]["armor_class"] = 0 if hit else 100
    seed = copy.deepcopy(next(a for a in me["action_catalog"] if a["display_name"] == "Broken-Rhythm Strike: Fu (Short Axe)"))
    seed.update(source_definition_id="test:review.seed_off_rhythm", display_name="Seed Off-Rhythm", economy="BONUS_ACTION")
    seed["parameters"]["typed"]["effects"] = [copy.deepcopy(OFF_RHYTHM_ROW)]
    me["action_catalog"].append(seed)
    me["actor_template"]["action_ids"].append(seed["source_definition_id"])
    me["bundle_sha256"] = canonical_sha256({k: v for k, v in me.items() if k != "bundle_sha256"})
    foe = compile_character(C._sheet("tianxia.sphere.athletics", items=C.AXE_ITEMS), actor_id=C.FOE)
    persistence = Gate4Persistence(C.ROOT, tmp_path)
    session = persistence.create_match(match_seed="C13-SWAY-PERSIST", typed_bundles=(me, foe),
        roster_setup={"primary_actor_ids": [C.ME, C.FOE], "team_by_actor": {C.ME: "team:a", C.FOE: "team:b"},
                      "starting_positions": {C.ME: {"x": 3, "y": 6}, C.FOE: {"x": 4, "y": 6}}})
    while session.engine.state.current_actor_id != C.ME:
        session.submit_intent(intent(session.engine, "End turn"), primary_decision_record=None, reaction_provider=None)
    session.submit_intent(intent(session.engine, "Seed Off-Rhythm", C.ME), primary_decision_record=None, reaction_provider=None)
    session.submit_intent(intent(session.engine, "End turn"), primary_decision_record=None, reaction_provider=None)
    assert session.engine.state.current_actor_id == C.FOE
    requests = []
    def provider(request):
        requests.append(request)
        options = request.get("legal_option_ids") or ()
        return accept(request, ["cell:3,5"] if str(request["reaction_source_id"]).endswith("drunken_swaying_step") else options[:1])
    session.submit_intent(intent(session.engine, "Fu (Short Axe) attack", C.FOE), primary_decision_record=None, reaction_provider=provider)
    loaded = persistence.load_match(session.match_id)
    defender = loaded.engine.state.actors[C.ME]
    assert SWAY_FLAG not in defender.turn_flags
    assert not defender.reaction_available
    assert (defender.position.x, defender.position.y) == ((3, 6) if hit else (3, 5))
    assert bool([r for r in requests if r["reaction_source_id"].endswith("drunken_swaying_step")]) is (not hit)
    assert loaded.verify()["status"] == "PASS"
