"""A manual decision must not build the AI profile; profile queries share weapon facts."""
from collections import Counter

from combat import ai_tactics, carry, read_queries, weapon_delivery
from combat.ext.item_lifecycle import is_destroyed, retirement_record
from combat.gate4_context import build_decision_context
from combat.target_knowledge import actors_for
from tests.test_auto_martial import SPEAR_KIT
from tests.test_tabletop_hunt6 import LEFT, HOLD, table_fight


def _old_weapons(engine, actor, words=(), *, include_busy=False, include_native=False):
    """The former item-of-per-action implementation, for mapping parity."""
    disabled = {c.data.get("disables_action") for c in actor.conditions.values()
                if retirement_record(c) or not include_busy or c.data.get("dropped_at") or c.data.get("held_by")
                or c.condition_id == "condition:typed.disarmed"}
    held = {c.data.get("disables_action") for owner in engine.state.actors.values()
            for c in owner.conditions.values() if c.data.get("held_by") == actor.entity_id
            and not is_destroyed(owner, key=str(c.data.get("item_key") or ""),
                                 weapon=str(c.data.get("disables_action") or ""))}
    carrying = carry.carrying_of(engine, actor.entity_id)
    result = {}
    for action in engine.action_catalog.values():
        if action.owner_id != actor.entity_id:
            continue
        source = action.source_definition_id
        item = carry.item_of(carrying, weapon_action=source)
        if item is not None and carry.quantity_exhausted(engine, actor, item):
            continue
        parameters = action.parameters or {}
        typed = parameters.get("typed") or {}
        if "#" in source or source in disabled or weapon_delivery.weapon_variant_base(parameters):
            continue
        if not typed.get("weapon"):
            declared = str(parameters.get("delivered_by") or "").split("#", 1)[0]
            if (include_native and declared
                    and not any(parameters.get(key) for key in ("weapon_source_id", "maneuver_of", "opportunity_of"))
                    and (not words or any(word in action.display_name.lower() for word in words))):
                result.setdefault(declared, action)
            continue
        if any(typed.get(key) for key in ("delivered_by", "weapon_source_id", "maneuver_of", "opportunity_of")):
            continue
        required = parameters.get("requires_held_weapon")
        if required and required not in held:
            continue
        if words and not any(word in action.display_name.lower() for word in words):
            continue
        result[source] = action
    return result


def test_manual_preview_and_commit_skip_ai_profile(tmp_path, monkeypatch):
    combat, _, mid = table_fight(tmp_path, [], kit=SPEAR_KIT)
    session = combat._load_session(mid)
    candidate = next(c for c in combat._legal_candidates(session) if c.source_definition_id == HOLD)
    payload = candidate.model_dump(mode="json", include={
        "candidate_id", "decision_id", "state_version", "actor_id", "target_ids", "destination", "option_ids"})
    calls = []
    original = ai_tactics.owned_profile

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(ai_tactics, "owned_profile", counted)
    preview = combat.preview(mid, payload, [], session=session)
    assert preview["status"] == "PREVIEW_COMPLETE"
    assert not calls
    result = combat.submit_intent(mid, payload, [], preview["preview_id"], session=session)
    assert result["preview_id"] == preview["preview_id"]
    assert not calls


def test_profile_shares_weapon_queries_and_preserves_results(tmp_path, monkeypatch):
    combat, _, mid = table_fight(tmp_path, [], kit=SPEAR_KIT)
    session = combat._load_session(mid)
    engine = session.engine
    actor = engine.state.actors[LEFT]
    carrying = carry.carried_identity(engine, LEFT)
    original_item = next(i for i in carrying["items"] if i.get("weapon_action") in engine.action_catalog)
    weapon = engine.action_catalog[original_item["weapon_action"]]
    for n in range(40):
        source = weapon.source_definition_id + f".synthetic{n}"
        engine.action_catalog[source] = weapon.model_copy(update={"source_definition_id": source}, deep=True)
        actor.action_ids += (source,)
        carrying["items"].append({**original_item, "key": f"synthetic{n}", "weapon_action": source})
    # First matching item must win, even when duplicate inventory rows disagree.
    carrying["items"].append({**original_item, "key": "duplicate", "quantity": 0})
    for words in ((), ("spear",), ("nonexistent",)):
        for busy in (False, True):
            for native in (False, True):
                kwargs = dict(include_busy=busy, include_native=native)
                assert weapon_delivery.available_weapons(engine, actor, words, **kwargs) == _old_weapons(
                    engine, actor, words, **kwargs)

    policy, _ = combat.policies.for_actor(LEFT)
    candidates = combat._legal_candidates(session, knowledge_only=True)
    context = build_decision_context(engine, policy, for_ai=True, prepared_candidates=candidates)
    known = actors_for(engine, actor)
    with read_queries.sharing_off():
        expected = ai_tactics.owned_profile(engine, actor, known, context.legal_candidates)
    assert context.tactics == expected

    calls = Counter()
    original = weapon_delivery._available_weapons

    def counted(engine, actor, words=(), *, include_busy=False, include_native=False):
        calls[(id(actor), tuple(words), include_busy, include_native)] += 1
        return original(engine, actor, words, include_busy=include_busy, include_native=include_native)

    monkeypatch.setattr(weapon_delivery, "_available_weapons", counted)
    assert ai_tactics.owned_profile(engine, actor, known, context.legal_candidates) == expected
    assert calls and all(count == 1 for count in calls.values())
