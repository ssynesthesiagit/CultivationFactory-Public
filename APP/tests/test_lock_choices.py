import pytest

from combat import ext
from combat.gate2_runtime_models import ActionIntent, ReactionDecision, Position, DiceSpec
from combat.gate4_context import build_reaction_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_models import LocalControllerPolicy
from combat.gate4_policy import PolicyLibrary
from combat.typed_executor import Context, block_attack, block_save
from tests.test_auto_tabik import _engine, ME, AN, ROOT


def intent(e, answers=()):
    c = next(c for c in e.legal_candidates() if c.kind == "END_TURN")
    return ActionIntent(intent_id="test:choices", decision_id=c.decision_id, candidate_id=c.candidate_id,
                        state_version=c.state_version, actor_id=ME, reaction_decisions=answers)


def install(monkeypatch, point, fn):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, point, [fn])


def test_dynamic_options_bounded_and_embedded_revalidated(monkeypatch):
    e, _ = _engine([])
    install(monkeypatch, "choice_options", lambda *args: {"option_ids": ["left", "right"], "automatic_use": True})
    requests = []
    def provider(request):
        requests.append(request)
        return ReactionDecision(checkpoint="BEFORE:1", reactor_id=AN, reaction_source_id="choice:step",
                                selection="USE", option_ids=("right",)), None
    e.set_reaction_provider(provider)
    d = e._reaction_decision(intent(e), "BEFORE:1", AN, "choice:step",
                             context={"actor_id": ME, "target_id": AN, "attack_index": 2})
    assert d.option_ids == ("right",)
    assert requests[0]["legal_option_ids"] == ["left", "right"]
    assert requests[0]["choice_trigger"]["attack_index"] == 2
    assert requests[0]["attacking_actor_id"] == ME
    for options in [("right", "left"), ("right", "right"), ("invented",), ()]:
        bad = d.model_copy(update={"option_ids": options})
        with pytest.raises(ValueError, match="invalid extension choice"):
            e._reaction_decision(intent(e, (bad,)), "BEFORE:1", AN, "choice:step")
    declined = d.model_copy(update={"selection": "DECLINE", "option_ids": ()})
    assert e._reaction_decision(intent(e, (declined,)), "BEFORE:1", AN, "choice:step").selection == "DECLINE"


def test_controller_selects_one_or_two_distinct_options(monkeypatch):
    e, _ = _engine([])
    policy = PolicyLibrary(ROOT).fallback()
    for maximum in (1, 2):
        context = build_reaction_context(e, policy, dict(checkpoint="test", reactor_id=ME,
            reaction_source_id="choice:exploit", legal_option_ids=["a", "b", "c"],
            extension_choice={"option_ids": ["a", "b", "c"], "minimum_selections": 1,
                              "maximum_selections": maximum, "automatic_use": True}))
        chosen = LocalDeterministicController().choose_reaction(context).decision
        assert chosen.option_ids == ("a", "b")[:maximum]
        assert chosen.spend == 0


def move(engine, defender, destination):
    previous = defender.position
    defender.position = destination
    engine._append_event("MOVEMENT_COMMITTED", "test:footwork", actor_id=defender.entity_id,
                         payload={"destination": destination.model_dump(mode="json"), "cost_ft": 0,
                                  "path": [previous.model_dump(mode="json"), destination.model_dump(mode="json")]})


@pytest.mark.parametrize("typed", [False, True])
def test_offturn_attack_checkpoint_moves_without_reaction_and_no_roll(monkeypatch, typed):
    e, _ = _engine([], foe_at=(4, 6))
    defender = e.state.actors[AN]
    defender.reaction_available = False
    calls = []
    def step(engine, attacker, target, request, context):
        calls.append(context)
        move(engine, target, Position(x=9, y=6))
        return {"mode": "DISADVANTAGE"}
    install(monkeypatch, "before_attack", step)
    n = len(e.rolls)
    actor = e.state.actors[ME]
    a = next(e.action_catalog[aid] for aid in actor.action_ids
             if e.action_catalog[aid].target_kind == "HOSTILE_ENTITY" and not e.action_catalog[aid].parameters.get("requires_condition"))
    a = a.model_copy(update={"range_ft": 5})
    if typed:
        ctx = Context(e, actor, a, intent(e), {"numbers": {"attack_bonus": 100}, "weapon": {"damage": {"count": 1, "sides": 4}}, "range_ft": 5}, [defender], defender)
        block_attack(ctx, {"type": "attack", "count": 1, "on_hit": []})
    else:
        assert not e._resolve_attack_spec(actor, defender, {"attack_bonus": 100, "reach_ft": 5,
            "damage": DiceSpec(count=1, sides=4), "damage_type": "SLASHING"}, intent(e), source_definition_id="test:attack")
    assert len(calls) == 1
    assert len(e.rolls) == n
    assert not defender.reaction_available
    assert e.state.current_actor_id == ME


@pytest.mark.parametrize("typed", [False, True])
def test_escape_dex_effect_skips_target_not_half_damage(monkeypatch, typed):
    e, _ = _engine([], foe_at=(4, 6))
    actor, target = e.state.actors[ME], e.state.actors[AN]
    def step(engine, subject, request, context):
        move(engine, subject, Position(x=12, y=6))
        return {"mode": "ADVANTAGE"}
    install(monkeypatch, "before_dex_save", step)
    hp, rolls = target.current_hp, len(e.rolls)
    if typed:
        a = next(iter(e.action_catalog.values())).model_copy(update={"range_ft": 5})
        ctx = Context(e, actor, a, intent(e), {"numbers": {"save_dc": 50}}, [target], target)
        block_save(ctx, {"ability": "DEX", "on_fail": [{"type": "damage", "flat": 20}], "on_success": [{"type": "half_damage"}]})
    else:
        assert e._roll_save(target, "DEX", 50, "test:save", target_check=lambda: e._distance_actor_to_actor(actor, target) <= 5) is None
    assert target.current_hp == hp
    assert len(e.rolls) == rolls


def test_decline_continues_both_attacks_and_choice_pause_rolls_back(monkeypatch):
    e, _ = _engine([], foe_at=(4, 6))
    install(monkeypatch, "before_attack", lambda *args: None)
    a, t = e.state.actors[ME], e.state.actors[AN]
    n = len(e.rolls)
    for index in (1, 2):
        e._resolve_attack_spec(a, t, {"attack_bonus": -100, "reach_ft": 5, "damage": None}, intent(e),
                               source_definition_id="test:attack", attack_index=index)
    assert len(e.rolls) == n + 2
    class NeedsChoice(Exception):
        pass
    def pause(*args):
        raise NeedsChoice()
    install(monkeypatch, "before_attack", pause)
    before = e.state.model_dump(mode="json")
    with pytest.raises(NeedsChoice):
        with e._transaction("test:attack", "test:pause", ME):
            e._resolve_attack_spec(a, t, {"attack_bonus": 1, "reach_ft": 5}, intent(e), source_definition_id="test:attack")
    assert e.state.model_dump(mode="json") == before


def test_provider_pause_unwinds_then_embedded_decline_resumes(monkeypatch):
    e, _ = _engine([], foe_at=(4, 6))
    install(monkeypatch, "choice_options", lambda *args: {"option_ids": ["step"]})
    checkpoints = []
    def before(engine, actor, target, request, context):
        checkpoint = "TYPED:FOOTWORK:" + str(context["attack_index"])
        checkpoints.append(checkpoint)
        d = engine._reaction_decision(request, checkpoint, target.entity_id, "choice:footwork", context=context)
        if d and d.selection == "USE":
            move(engine, target, Position(x=9, y=6))
            return {"mode": "DISADVANTAGE"}
    install(monkeypatch, "before_attack", before)
    class Paused(Exception):
        pass
    def provider(request):
        raise Paused(request)
    e.set_reaction_provider(provider)
    c = next(c for c in e.legal_candidates() if c.target_ids == (AN,) and c.kind == "ACTION"
             and e.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("weapon"))
    request = ActionIntent(intent_id="test:pause", decision_id=c.decision_id, candidate_id=c.candidate_id,
                           state_version=c.state_version, actor_id=ME, target_ids=c.target_ids)
    before_state = e.state.model_dump(mode="json")
    with pytest.raises(Paused):
        e.execute_intent(request)
    assert e.state.model_dump(mode="json") == before_state
    declined = ReactionDecision(checkpoint=checkpoints[-1], reactor_id=AN, reaction_source_id="choice:footwork", selection="DECLINE")
    e.execute_intent(request.model_copy(update={"reaction_decisions": (declined,)}))
    assert any(ev.event_type == "ATTACK_ROLLED" for ev in e.events)
