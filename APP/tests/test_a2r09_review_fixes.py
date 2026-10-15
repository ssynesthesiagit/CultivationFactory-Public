"""Regressions for the A2R09 Sol review; no live models or browser required."""
from types import SimpleNamespace

import pytest

from combat.gate2_runtime_models import Position
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE

NINPO = "tianxia.subpath.qi.ninpo_adept.feature."
QI = "tianxia.path.qi_cultivation.feature."


def add_fixture_action(bundle, name, effects, *, target="SELF", **parameters):
    """Seal fixture payloads before the match; table reloads discard engine edits."""
    from combat.canonical import canonical_sha256
    source = "action:test.a2r09f2." + name.lower().replace(" ", "_")
    bundle["action_catalog"].append({
        "source_definition_id": source, "display_name": name, "owner_id": bundle["actor_id"],
        "economy": "NONE", "resolution_kind": "TYPED", "target_kind": target, "range_ft": 100,
        "parameters": {"free_primary": True, "typed": {"source": source, "effects": effects, "numbers": {"save_dc": 20},
                                  "duration": {"kind": "instant"}, "riders": []}, **parameters}})
    bundle["actor_template"]["action_ids"].append(source)
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def ninja_table(tmp_path, *, neutral=False):
    def setup(bundles):
        owner = bundles[0]
        for action in owner["action_catalog"]:
            if action["display_name"] == "Unarmed Strike":
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        add_fixture_action(owner, "Project Armament", [{"type": "condition", "condition": "domain_armament",
                           "applies_to": "self", "expires_on": "UNTIL_REMOVED",
                           "condition_data": {"ax": 8, "ay": 6, "reach_ft": 60}}])
        add_fixture_action(owner, "Place Smoke", [{"type": "move_zone", "zone_name": "Smoke Veil", "max_ft": 100}],
                           target="CELL", any_cell=True)
    return fixture(tmp_path, [], primary="Qi", owner_path="Qi Cultivation", seed="A2R09F2", bundle_transform=setup,
                   battlefield_transform=lambda arena: arena.update(terrain_regions=[]),
                   owner_features=[NINPO + "shadow_clone_array", NINPO + "smoke_veil"],
                   team_overrides={ALLY: "team:neutral"} if neutral else None,
                   positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 2, "y": 6}, FOE: {"x": 4, "y": 6}})


def strike(combat, table, mid, picks):
    engine = combat._load_session(mid).engine
    attack = next(c for c in engine.legal_candidates()
                  if c.actor_id == OWNER and c.target_ids == (FOE,)
                  and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", "") == "Unarmed Strike")
    return settle(table, mid, attack.candidate_id, picks=picks)


def test_armament_misdirection_table_preserves_all_distant_destinations(tmp_path):
    from combat.ext import qi_path

    combat, table, mid = ninja_table(tmp_path)
    settle(table, mid, candidate(combat, mid, "Shadow Clone Array").candidate_id)
    settle(table, mid, candidate(combat, mid, "Project Armament").candidate_id)
    prompts = strike(combat, table, mid, {"choice:needle.clone_misdirection": "armament",
                                         "choice:needle.clone_armament": "cell:11,6"})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.clone_armament")
    options = {o["id"] for o in prompt["choice"]["options"]}
    assert len(options) > 16 and "cell:11,6" in options
    assert "cell:3,3" not in options  # owner-near but too far from the Armament
    loaded = reload(tmp_path, mid)
    assert qi_path.armament_point(loaded.state.actors[OWNER]) == (11, 6)


def test_armament_misdirection_nearby_destination_executes_without_name_error(tmp_path):
    from combat.ext import qi_path

    combat, table, mid = ninja_table(tmp_path)
    settle(table, mid, candidate(combat, mid, "Shadow Clone Array").candidate_id)
    settle(table, mid, candidate(combat, mid, "Project Armament").candidate_id)
    strike(combat, table, mid, {"choice:needle.clone_misdirection": "armament",
                                "choice:needle.clone_armament": "cell:4,5"})
    assert qi_path.armament_point(reload(tmp_path, mid).state.actors[OWNER]) == (4, 5)


@pytest.mark.parametrize("domain_origin", [False, True])
def test_smoke_misdirection_table_uses_zone_origin_and_control_range(tmp_path, domain_origin):
    from combat.ext.tabik_dark import movable

    combat, table, mid = ninja_table(tmp_path)
    settle(table, mid, candidate(combat, mid, "Shadow Clone Array").candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    if domain_origin:
        settle(table, mid, candidate(combat, mid, "Project Armament").candidate_id)
    settle(table, mid, candidate(combat, mid, "Smoke Veil", at=(8 if domain_origin else 7, 6)).candidate_id)
    engine = combat._load_session(mid).engine
    zone = movable(engine, engine.state.actors[OWNER], "Smoke Veil")[0]
    settle(table, mid, candidate(combat, mid, "Place Smoke", at=(13, 6)).candidate_id)
    destination = 17 if domain_origin else 15
    prompts = strike(combat, table, mid, {"choice:needle.clone_misdirection": "smoke",
                                         "choice:needle.clone_smoke_veil": f"cell:{destination},6"})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.clone_smoke_veil")
    options = {o["id"] for o in prompt["choice"]["options"]}
    assert len(options) > 16 and f"cell:{destination},6" in options
    assert "cell:13,6,1" in options  # cultivated smoke can move vertically too
    if not domain_origin:
        assert "cell:16,6" not in options  # outside 60 feet from the owner
    assert "cell:4,6" not in options  # too far from the moved zone
    loaded = reload(tmp_path, mid)
    assert loaded.state.zones[zone.zone_id].center == Position(x=destination, y=6)


def test_smoke_recipients_include_hostile_and_neutral_creatures(tmp_path):
    combat, table, mid = ninja_table(tmp_path, neutral=True)
    prompts = settle(table, mid, candidate(combat, mid, "Smoke Veil", at=(5, 6)).candidate_id,
                     picks={"choice:needle.smoke_veil_viewers": [ALLY, FOE]})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.smoke_veil_viewers")
    assert {ALLY, FOE} <= {o["id"] for o in prompt["choice"]["options"]}
    loaded = reload(tmp_path, mid)
    zone = next(z for z in loaded.state.zones.values() if z.owner_id == OWNER and z.active)
    assert set(zone.trigger_profile["lightly_obscured_viewer_ids"]) == {ALLY, FOE}


@pytest.mark.parametrize("visible", [False, True])
def test_ai_smoke_recipients_offer_every_perceived_creature_only(monkeypatch, visible):
    from combat.ext import needle
    from tests.test_auto_ninpo_residual import _ninja, _act, ME, FOE as NFOE

    engine = _ninja()
    engine.typed_control_modes = {ME: "LOCAL_AUTO"}
    if not visible:
        engine._apply_condition(engine.state.actors[NFOE], "condition:typed.invisible", "test:invisible", NFOE,
                                expires_on="UNTIL_REMOVED", data={})
    offered = []
    original = needle.ask
    def choose(*args, **kwargs):
        if args[4] == "choice:needle.smoke_veil_viewers":
            offered.extend(args[5])
            return []
        return original(*args, **kwargs)
    monkeypatch.setattr(needle, "ask", choose)
    _act(engine, "Smoke Veil", at=(4, 6))
    assert (NFOE in offered) == visible


def test_failed_analyze_qi_retry_is_blocked_after_turn_refresh_and_cold_reload(tmp_path, monkeypatch):
    from combat.ext import ability_source, qi_sensing

    monkeypatch.setattr(ability_source, "cultivation_check_detail", lambda *a, **kw: (0, False))
    def setup(bundles):
        add_fixture_action(bundles[0], "Conceal Qi", [{"type": "condition", "condition": "concealed",
                           "applies_to": "target", "expires_on": "UNTIL_REMOVED",
                           "condition_data": {"label": "Qi concealment"}}], target="ANY_CREATURE")
    combat, table, mid = fixture(tmp_path, [], primary="Qi", owner_path="Qi Cultivation", bundle_transform=setup,
                               owner_features=[QI + "qi_sensing"], seed="A2R09F2-QI")
    settle(table, mid, candidate(combat, mid, "Conceal Qi", target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, "Analyze Qi", target=FOE).candidate_id)
    assert any(c.condition_id == "condition:typed.analyze_qi_failed"
               for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())
    # Actually refresh Action economy on a subsequent turn before testing the veto.
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    actor, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert actor.action_available
    action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.display_name == "Analyze Qi")
    assert not any(c.source_definition_id == action.source_definition_id and FOE in c.target_ids
                   for c in engine.legal_candidates())
    before = engine.state.model_dump(mode="json")
    assert qi_sensing.analyze_qi_candidate(engine, actor, SimpleNamespace(target_ids=(FOE,)), action) is False
    assert engine.state.model_dump(mode="json") == before
    target.conditions[next(k for k, c in target.conditions.items() if c.condition_id == "condition:typed.concealed")].data["label"] = "Changed concealment"
    before = engine.state.model_dump(mode="json")
    assert qi_sensing.analyze_qi_candidate(engine, actor, SimpleNamespace(target_ids=(FOE,)), action) is True
    assert engine.state.model_dump(mode="json") == before


def test_analyze_qi_dc_uses_concealing_source_then_targets_own_numbers(monkeypatch):
    from combat.ext import qi_sensing, ability_source
    from tests.test_auto_a2r11_residual import _qi, ME, FOE as QFOE, use

    engine, observer, target = _qi(["qi_sensing"])
    target.position = Position(x=4, y=6)
    engine._apply_condition(target, "condition:typed.concealed", "test:veil", QFOE,
                            expires_on="UNTIL_REMOVED", data={})
    own_action = next(a for a in engine.action_catalog.values() if a.owner_id == QFOE and a.parameters.get("typed"))
    for action in engine.action_catalog.values():
        if action.owner_id == QFOE and action.parameters.get("typed"):
            action.parameters["typed"]["numbers"] = {"key_mod": 4}
    expected = 8 + target.proficiency_bonus + 4
    dcs = []
    monkeypatch.setattr(ability_source, "cultivation_check_detail", lambda e, a, n, dc, *rest: (dcs.append(dc) or 0, True))
    analyze = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Analyze Qi")
    for mod in (1, 9):
        analyze.parameters["typed"]["numbers"]["key_mod"] = mod
        engine.state.actors[ME].action_available = True
        use(engine, "Analyze Qi", target=QFOE)
    assert dcs == [expected, expected]
    condition = next(c for c in target.conditions.values() if c.condition_id == "condition:typed.concealed")
    condition.source_definition_id = analyze.source_definition_id
    analyze.parameters["typed"]["numbers"]["save_dc"] = 23
    assert qi_sensing._concealment_dc(engine, target) == 23


def test_analyze_qi_query_is_pure_and_execution_preserves_other_failure_receipts():
    from combat.ext import qi_sensing
    from tests.test_auto_a2r11_residual import _qi, ME, FOE as QFOE

    engine, observer, target = _qi(["qi_sensing"])
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Analyze Qi")
    for target_id in (QFOE, ME):
        engine._apply_condition(observer, "condition:typed.analyze_qi_failed", action.source_definition_id, ME,
                                expires_on="UNTIL_REMOVED", data={"target": target_id, "concealment": "old effect"})
    before = engine.state.model_dump(mode="json")
    assert qi_sensing.analyze_qi_candidate(engine, observer, SimpleNamespace(target_ids=(QFOE,)), action) is True
    assert engine.state.model_dump(mode="json") == before
    # No concealment remains on this target: executing the successful analysis
    # removes its stale receipt but must preserve another target's failed check.
    qi_sensing.analyze_qi(SimpleNamespace(engine=engine, actor=observer, target=target,
                                        source=action.source_definition_id, rider=lambda text: None), {})
    receipts = [c.data["target"] for c in observer.conditions.values()
                if c.condition_id == "condition:typed.analyze_qi_failed"]
    assert receipts == [ME]


def test_forced_3d_route_stops_after_zone_relocation(monkeypatch):
    from combat import zones
    from combat.ext.rider_movement import forced_route_3d
    from tests.test_auto_ninpo_residual import _ninja, ME, FOE as NFOE

    engine = _ninja()
    actor = engine.state.actors[ME]
    origin = actor.position
    path = [origin, Position(x=3, y=7), Position(x=3, y=8)]
    relocated = Position(x=2, y=7)
    visits = []
    def entry(e, subject, old, new, **kw):
        visits.append(new)
        subject.position = relocated
    monkeypatch.setattr(zones, "on_moved", entry)
    forced_route_3d(engine, actor, path, "test:route", engine.state.actors[NFOE])
    assert actor.position == relocated
    assert visits == [path[1]]


@pytest.mark.parametrize("teleport", [False, True])
@pytest.mark.parametrize("trigger", ["walking", "teleport", "combined"])
def test_teleport_reactions_distinguish_walking_and_combined_triggers(teleport, trigger):
    from combat import typed_reactions
    from tests.test_auto_ninpo_residual import _ninja, ME, FOE as NFOE

    engine = _ninja()
    row = {"feature_id": "test:movement-answer", "block": "generic", "name": "Movement answer",
           "kind": "moved", "free": True, "range_ft": 60,
           "teleport_only": trigger == "teleport", "covers_teleport": trigger != "walking",
           "effects": [], "numbers": {}, "costs": []}
    engine.typed_reaction_rows[ME] = [row]
    typed_reactions.on_creature_event(engine, engine.state.actors[NFOE], "moved", moved_ft=5, teleport=teleport)
    answered = any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == row["feature_id"] for e in engine.events)
    assert answered == (trigger == "combined" or teleport == (trigger == "teleport"))
