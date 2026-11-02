import pytest

from combat.gate2_runtime_models import Position, DiceSpec
from combat.typed_executor import Context, block_attack
from tests.test_auto_tabik import _engine, ME, AN
from tests.test_lock_choices import install, intent

BODY = "test:bodyguard"


def setup(monkeypatch, cover=0):
    e, _ = _engine([], foe_at=(4, 6))
    original = e.state.actors[AN]
    body = original.model_copy(deep=True, update={"entity_id": BODY, "position": Position(x=4, y=7),
        "team_id": e.state.actors[ME].team_id, "reaction_ids": (), "current_hp": 100, "maximum_hp": 100})
    e.state.actors[BODY] = body
    e.actor_footprints[BODY] = e.actor_footprints[AN]
    calls = []
    def redirect(engine, actor, target, request, context):
        calls.append(context)
        return {"source_id": "test:intercept", "target_id": BODY, "cover_bonus": cover}
    install(monkeypatch, "retarget_attack", redirect)
    install(monkeypatch, "d20_result", lambda *a: {"source_id": "test:roll", "operation": "replace", "natural_result": 10})
    return e, e.state.actors[ME], original, body, calls


def test_typed_damage_rider_and_pre_roll_checkpoint_follow_effective_target(monkeypatch):
    e, a, original, body, calls = setup(monkeypatch)
    targets = []
    install(monkeypatch, "before_attack", lambda eng, actor, target, *rest: targets.append(target.entity_id))
    action = next(e.action_catalog[aid] for aid in a.action_ids if e.action_catalog[aid].target_kind == "HOSTILE_ENTITY")
    old_hp = original.current_hp
    ctx = Context(e, a, action, intent(e), {"numbers": {"attack_bonus": 100}, "range_ft": 5}, [original], original)
    block_attack(ctx, {"type": "attack", "count": 1,
        "on_hit": [{"type": "damage", "flat": 3}, {"type": "condition", "condition": "prone"}]})
    assert len(calls) == 1 and targets == [BODY]
    assert original.current_hp == old_hp and body.current_hp < 100
    assert any(c.condition_id.endswith("prone") for c in body.conditions.values())
    assert not any(c.condition_id.endswith("prone") for c in original.conditions.values())
    assert next(ev for ev in reversed(e.events) if ev.event_type == "ATTACK_ROLLED").target_ids == (BODY,)


def test_legacy_return_target_and_cover_apply_to_this_attack_only(monkeypatch):
    e, a, original, body, _ = setup(monkeypatch, 5)
    spec = {"attack_bonus": body.armor_class - 10, "range_ft": 5}
    assert not e._resolve_attack_spec(a, original, spec, intent(e), source_definition_id="test:attack")
    rolled = next(ev for ev in reversed(e.events) if ev.event_type == "ATTACK_ROLLED")
    assert rolled.payload["cover_bonus"] == 5 and spec["resolved_target_id"] == BODY
    install(monkeypatch, "retarget_attack", lambda *a: None)
    e._resolve_attack_spec(a, original, {"attack_bonus": 100, "range_ft": 5}, intent(e), source_definition_id="test:attack")
    assert next(ev for ev in reversed(e.events) if ev.event_type == "ATTACK_ROLLED").payload["cover_bonus"] == 0


def test_invalid_target_rolls_back_and_consumes_no_roll(monkeypatch):
    e, a, original, body, _ = setup(monkeypatch)
    body.position = Position(x=15, y=15)
    before, counter = e.state.model_dump(), e.roller.counter
    with pytest.raises(ValueError, match="illegal redirected"):
        with e._transaction("test:attack", "test:redirection", ME):
            e._resolve_attack_spec(a, original, {"range_ft": 5}, intent(e), source_definition_id="test:attack")
    assert e.state.model_dump() == before and e.roller.counter == counter


def test_legacy_attack_then_save_uses_bodyguard(monkeypatch):
    e, a, original, body, _ = setup(monkeypatch)
    action = e.action_catalog["action:an_eui.scouring_destruction_blast"].model_copy(update={"attack_bonus": 100})
    e._resolve_attack_then_save(a, original, action, intent(e))
    saves = [r for r in e.rolls if r.reason.startswith("SAVE:")]
    assert saves and saves[-1].actor_id == BODY


def test_c3_attack_uses_redirected_target(monkeypatch):
    e, a, original, body, calls = setup(monkeypatch)
    from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
    runtime = CharacterCombatRuntimeEngine.__new__(CharacterCombatRuntimeEngine)
    runtime.__dict__.update(e.__dict__)
    hp = original.current_hp
    assert runtime._resolve_character_attack(a, original, source_id="test:c3", attack_bonus=100,
        damage=None, fixed_damage=3, damage_type="FIRE", intent=intent(e), ranged=False)
    assert len(calls) == 1 and body.current_hp == 97 and original.current_hp == hp


def test_second_attack_context_returns_to_original_target(monkeypatch):
    e, a, original, body, _ = setup(monkeypatch)
    def once(engine, actor, target, request, context):
        if context["attack_index"] == 1:
            return {"source_id": "test:intercept", "target_id": BODY}
    install(monkeypatch, "retarget_attack", once)
    seen = []
    install(monkeypatch, "after_hit", lambda ctx, target, kind: seen.append((target.entity_id, ctx.target.entity_id)))
    action = next(e.action_catalog[aid] for aid in a.action_ids if e.action_catalog[aid].target_kind == "HOSTILE_ENTITY")
    block_attack(Context(e, a, action, intent(e), {"numbers": {"attack_bonus": 100}, "range_ft": 5}, [original], original),
        {"type": "attack", "count": 2, "on_hit": [{"type": "damage", "flat": 1}]})
    assert seen == [(BODY, BODY), (AN, AN)]
