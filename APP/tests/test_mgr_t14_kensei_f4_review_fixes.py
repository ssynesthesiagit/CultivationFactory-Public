"""Focused Kensei F4 regressions for native option and combat boundaries."""
from types import SimpleNamespace


def test_sword_draws_attack_mode_is_pure_until_actual_roll():
    from combat.ext import kensei
    condition = SimpleNamespace(condition_id=kensei.FIRST_ATTACK, instance_id="first")
    actor = SimpleNamespace(conditions={"first": condition})
    engine = SimpleNamespace(state=SimpleNamespace(round_number=1))
    ctx = SimpleNamespace(engine=engine, actor=actor)
    assert kensei.sword_draws_first_attack(ctx, SimpleNamespace(entity_id="target")) == "ADVANTAGE"
    assert actor.conditions["first"] is condition


def test_body_extra_attack_suppression_applies_without_kensei_metadata(monkeypatch):
    from combat.ext import body_modes_scene_resources as body
    source = "tianxia.path.body_refining.feature.body_extra_attack"
    monkeypatch.setattr(body, "bundle_of", lambda engine, actor: {
        "body_mode_level": 6, "cl": 6, "body_feature_levels": {source: 5}})
    monkeypatch.setattr(body, "available", lambda *args: False)
    monkeypatch.setattr(body, "effective_body_cl", lambda *args: 4)
    from combat import typed_reactions
    monkeypatch.setattr(typed_reactions, "attacks_for_cl", lambda table, cl: table["1"])
    actor = SimpleNamespace(entity_id="owner")
    engine = SimpleNamespace(typed_passive_rows={"owner": [{"block": "extra_attack", "feature_id": source, "attacks": 2}]})
    ctx = SimpleNamespace(typed={}, engine=engine, actor=actor)
    assert body.body_suppressed_extra_attack_count(ctx, {"type": "attack"}, 3) == 1


def test_kensei_object_provider_does_not_veto_other_legal_profiles(monkeypatch):
    from combat.ext import kensei
    owner = SimpleNamespace(entity_id="owner")
    source_action = SimpleNamespace(owner_id="owner", parameters={"kensei_object_origin": "unarmed"})
    other = SimpleNamespace(parameters={"object_attack": True})
    engine = SimpleNamespace(action_catalog={"native": source_action})
    monkeypatch.setattr(kensei, "_rows", lambda *args: [object()])
    assert kensei.kensei_object_candidates(engine, owner, object(), other) is None


def test_sword_draws_builds_separate_walk_and_fly_grants(monkeypatch):
    from combat.ext import kensei
    from combat import granted_movement, flight
    from combat.ext import needle
    calls, resolved = [], []
    monkeypatch.setattr(flight, "profile", lambda engine, actor: SimpleNamespace(speed_ft=40))
    walk_cell, fly_cell = object(), object()
    def routes(engine, mover, feet, mode=None):
        calls.append((feet, mode))
        if mode == "walk":
            return {walk_cell: ((walk_cell,), feet, "walk")}
        if mode == "fly":
            return {fly_cell: ((fly_cell,), feet, "fly")}
        return {}
    monkeypatch.setattr(granted_movement, "routes", routes)
    monkeypatch.setattr(needle, "cell_id", lambda cell, include_altitude=False: "walk" if cell is walk_cell else "fly")
    monkeypatch.setattr(needle, "checkpoint_id", lambda *args: "checkpoint")
    monkeypatch.setattr(needle, "ask", lambda *args, **kwargs: ["fly"])
    monkeypatch.setattr(granted_movement, "resolve_path", lambda *args, **kwargs: resolved.append((args[2], kwargs["mode"])) or True)
    engine = SimpleNamespace()
    mover = SimpleNamespace(position=SimpleNamespace(z=0), entity_id="owner", display_name="Owner")
    ctx = SimpleNamespace(engine=engine, intent=None)
    assert kensei._move(ctx, mover, {"walk": 15, "fly": 20}, "choice", "Sword Draws")
    assert calls == [(15, "walk"), (20, "fly")]
    assert resolved == [((fly_cell,), "fly")]


def test_sword_saint_reach_excludes_unavailable_reach_weapon(monkeypatch):
    from combat.ext import kensei, reach_bonus, hand_occupancy
    owner = SimpleNamespace(entity_id="owner")
    long = SimpleNamespace(owner_id="owner", parameters={"typed": {"effects": [{"type": "attack"}], "weapon": {"source": "stowed"}}})
    natural = SimpleNamespace(owner_id="owner", parameters={"typed": {"effects": [{"type": "attack", "attack_kind": "unarmed"}]}})
    engine = SimpleNamespace(action_catalog={"long": long, "natural": natural})
    monkeypatch.setattr(reach_bonus, "current_reach", lambda engine, actor, action, **kwargs: 15 if action is long else 5)
    monkeypatch.setattr(hand_occupancy, "weapon_allowed", lambda engine, actor, action: False if action is long else None)
    assert kensei._usable_melee_reach(engine, owner) == 5
