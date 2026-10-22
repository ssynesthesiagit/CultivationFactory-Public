"""Disabled human riders cannot reappear through an embedded paid variant.

Synthetic sheets and an offline ranking client only. Real settings commits and
reloads cover the same table path as the Life-Severing Sword regression.
"""
import json
from types import SimpleNamespace

import pytest

from combat import embedding_rank, menu_rank
from combat.ext.attack_modifiers import CONDITION, enabled_variant, variant_replaced
from combat.placement_menu import query as placement_query
from tests.hunt36_support import LEFT, RIGHT, fight, reload, send, turn


@pytest.mark.parametrize("mode", ["MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"])
@pytest.mark.parametrize("owned", [
    ["WATER_BASE_WATER_LASH", "TAL_WATER_PULL_OF_THE_RIVER"],
    ["tianxia.path.body_refining.feature.iron_fist", "TAL_VOID_NULLIFYING_STRIKE"],
])
def test_off_on_off_preserves_every_other_route_and_restores_exact_variants(tmp_path, monkeypatch, mode, owned):
    def offline(*args, **kwargs):
        raise OSError("offline test transport")
    monkeypatch.setattr(menu_rank, "_CLIENT", embedding_rank.EmbeddingClient(transport=offline))
    combat, table, mid = fight(tmp_path, owned, primary="Stamina", cl=5,
                               seed="DISABLED-RIDER", positions={
                                   LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 6, "y": 6}})
    turn(combat, table, mid)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode=mode)
    engine = reload(combat, mid)
    variants = {a.source_definition_id for a in engine.action_catalog.values()
                if a.owner_id == LEFT and variant_replaced(a, engine.action_catalog.values())}
    assert variants
    toggles = [a.source_definition_id for a in engine.action_catalog.values()
               if a.owner_id == LEFT and (a.parameters.get("attack_modifier_setting") or {}).get("field") == "on"]
    assert toggles

    def routes():
        engine = reload(combat, mid)
        native_sources = {c.source_definition_id for c in engine.legal_candidates()}
        with placement_query():
            candidates = engine.legal_candidates()
        assert {c.source_definition_id for c in candidates} == native_sources
        state = table.state(mid)
        menu = state["menu"]
        offered = {o["candidate_id"] for g in menu["actions"] for o in g["options"]}
        offered.update(o["candidate_id"] for o in menu["moves"])
        offered.add(menu["end_turn"])
        assert offered == {c.candidate_id for c in candidates}
        assert set(toggles) <= {c.source_definition_id for c in candidates}
        return {json.dumps(c.model_dump(mode="json", exclude={
            "candidate_id", "decision_id", "state_version", "metadata"}), sort_keys=True)
                for c in candidates}, {c.source_definition_id for c in candidates}

    def toggle_all():
        for source in toggles:
            engine = combat._load_session(mid).engine
            send(combat, table, mid, next(c.candidate_id for c in engine.legal_candidates()
                                        if c.source_definition_id == source))

    off, sources = routes()
    assert not sources & variants, "an off-by-default rider was offered as a paid attack"
    toggle_all()
    on, sources = routes()
    assert sources & variants, "turning the rider on must restore its exact paid variants"
    assert off == {row for row in on if json.loads(row)["source_definition_id"] not in variants}
    toggle_all()
    off_again, sources = routes()
    assert off_again == off
    assert not sources & variants, "a committed and reloaded off choice must govern the table"

    # Built-in AI keeps the documented legacy variants despite the saved off
    # preferences. A model pilot on a human seat uses the human gate above.
    for auto_mode in ("LOCAL_AUTO", "API_AUTO"):
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode=auto_mode)
        engine = reload(combat, mid)
        with placement_query():
            candidates = engine.legal_candidates()
        ai = {json.dumps(c.model_dump(mode="json", exclude={
            "candidate_id", "decision_id", "state_version", "metadata"}), sort_keys=True)
              for c in candidates}
        assert {row for row in on if json.loads(row)["source_definition_id"] in variants} <= ai


def fixture(*, modifiers=("one", "two"), controls=("one", "two"), saved=(), mode="MANUAL", legacy=False, owner_id=None):
    parent = SimpleNamespace(source_definition_id="parent", owner_id="actor",
        parameters={"typed": {"attack_modifier_loadout": [
            {"id": key, "legacy_paid": legacy} for key in modifiers]}})
    action = SimpleNamespace(source_definition_id="variant", owner_id="actor",
        parameters={"typed": {"attack_modifier_variant": "parent",
            "selected_modifiers": [{"id": "+".join(modifiers)}]}})
    actions = {row.source_definition_id: row for row in (parent, action)}
    for key in controls:
        actions[key] = SimpleNamespace(source_definition_id=key, owner_id="actor",
            parameters={"attack_modifier_setting": {"family": "parent", "modifier": key, "field": "on"}})
    actor = SimpleNamespace(entity_id="actor", owner_id=owner_id, conditions={
        key: SimpleNamespace(condition_id=CONDITION, data={
            "family": "parent", "modifier": key, "on": on})
        for key, on in saved})
    engine = SimpleNamespace(action_catalog=actions, typed_control_modes={"actor": mode})
    return engine, actor, action


@pytest.mark.parametrize("saved,expected", [
    ((), False), ((("one", 1),), False),
    ((("one", 1), ("two", 0)), False),
    ((("one", 1), ("two", 1)), None),
])
def test_composed_variant_requires_every_owned_control_on(saved, expected):
    engine, actor, action = fixture(saved=saved)
    assert enabled_variant(engine, actor, None, action) is expected


def test_control_lookup_uses_actor_entity_id_when_owner_differs():
    engine, actor, action = fixture(owner_id="distinct-owner")
    assert enabled_variant(engine, actor, None, action) is False


@pytest.mark.parametrize("mode", ["LOCAL_AUTO", "API_AUTO", None])
def test_no_recorded_human_keeps_legacy_candidates(mode):
    engine, actor, action = fixture(mode=mode)
    assert enabled_variant(engine, actor, None, action) is None


def test_no_owned_replacement_and_legacy_paid_defaults_remain_inert():
    engine, actor, action = fixture(controls=())
    assert not variant_replaced(action, engine.action_catalog.values())
    assert enabled_variant(engine, actor, None, action) is None
    engine, actor, action = fixture(legacy=True)
    assert enabled_variant(engine, actor, None, action) is None
    engine, actor, action = fixture(legacy=True, saved=(("one", 0),))
    assert enabled_variant(engine, actor, None, action) is False
    action.owner_id = "someone_else"
    assert enabled_variant(engine, actor, None, action) is None
