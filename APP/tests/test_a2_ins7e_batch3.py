"""CL15 Qi-Tempered Concentration through native saves and table cold replay."""
import pytest

from combat.ext import qi_tempered as plug, qi_path
from tests.auto_worker1_support import LEFT, RIGHT, act, cell_send, fight, reload, resolve, turn


def fresh(c, mid):
    session = c._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return reload(c, mid)


def fixture(tmp_path, *, owns=True, nascent=True, qi=False, cultivation=True, cl=15, ai=False, con=9, disabled=False, vertical=False, extra_witness=False):
    def sheet(doc, aid):
        if aid == LEFT:
            doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [plug.FEATURE] if owns else []
    def bundle(b):
        if b["actor_id"] == LEFT:
            if vertical:
                b["actor_template"].update(fly_speed_ft=50, hover=True, climb_speed_ft=50,
                                           speed_ft=50, strength_score=24)
            b["actor_template"]["saving_throws"]["CON"] = con
            if disabled:
                row = next(r for r in b["typed_reactions"] if r["feature_id"] == plug.NASCENT)
                row["held_back"] = True
            a = next(a for a in b["action_catalog"] if a["display_name"] == "Prepare")
            a["concentration"] = True
            a["parameters"]["typed"]["duration"] = {"kind": "until_removed", "concentration": True}
            if cultivation:
                a["parameters"]["typed"]["sphere"] = "tianxia.sphere.force"
    owned = ([plug.NASCENT] if nascent else []) + [qi_path.ARMAMENT]
    def arena(document):
        if vertical:
            from combat.tabletop import normalize_map, to_battlefield
            from tests.test_walkable_roofs import roof_document
            document.update(to_battlefield(normalize_map(roof_document())))
    c, t, mid = fight(tmp_path, owned, cl=cl, sheet_edit=sheet, bundle_edit=bundle,
        arena_edit=arena if vertical else None,
        extra_witness=extra_witness,
        positions={LEFT: {"x": 3, "y": 2}, RIGHT: {"x": 2, "y": 2}} if vertical else None,
        left_pb=20, reaction_ask=True, prepare_target="SELF",
        prepare_costs=[(plug.QI, 1)] if qi else [],
        prepare=[{"type": "condition", "condition": "test_maintained", "applies_to": "self",
                  "duration": {"kind": "until_removed"}}],
        cause=[{"type": "damage", "flat": 100, "damage_types": ["force"], "applies_to": "target"}])
    resolve(lambda a: act(t, mid, "Prepare", a))
    resolve(cell_send(t, mid, "Domain Armament: Manifest", (2, 4) if vertical else (2, 5) if extra_witness else (3, 5)))
    turn(t, mid, RIGHT)
    if ai:
        c.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    return c, t, mid


@pytest.mark.parametrize("mode", ["jump", "climb", "fly"])
def test_free_move_keeps_native_modes_sharing_endpoint_and_no_oa(tmp_path, mode):
    c, t, mid = fixture(tmp_path, vertical=True)
    before = fresh(c, mid).state.actors[LEFT].movement_remaining_ft
    answers, seen = [], False
    for _ in range(12):
        result = act(t, mid, "Cause", answers, target_id=LEFT)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        q = result["reaction"]
        source = q["context"]["reaction_source_id"]
        opts = q["choice"]["options"]
        if source == plug.MOVE_CHOICE:
            matching = [o for o in opts if "(3, 2), 5 feet high" in o["label"]]
            assert {"Jump", "Climb", "Fly"} <= {o["label"].split()[0] for o in matching}
            selected = [next(o["id"] for o in matching if o["label"].startswith(mode.capitalize()))]
            seen = True
        elif source == plug.BENEFIT_CHOICE:
            selected = ["move"]
        elif source == plug.INDEPENDENT_CHOICE:
            selected = ["maintain"]
        else:
            selected = [opts[0]["id"]]
        answers.append({**q["context"], "selection": "USE", "option_ids": selected})
    else:
        raise AssertionError("too many movement choices")
    assert seen
    e = fresh(c, mid)
    events = [ev for ev in e.events if ev.event_type == "MOVEMENT_COMMITTED" and ev.actor_id == LEFT]
    assert events and events[-1].payload["movement_mode"] == mode
    assert e.state.actors[LEFT].movement_remaining_ft == before
    assert not [ev for ev in e.events if ev.event_type == "REACTION_RESOLVED" and ev.actor_id == RIGHT]


def test_free_move_exempts_two_legacy_reactors_and_restores_scope(tmp_path, monkeypatch):
    from combat.ext import granted_movement
    from combat.gate2_runtime_content import BASIC_MELEE, AN
    from combat.gate2_runtime_models import Position
    witness = "actor:factory.auto111-witness"
    c, t, mid = fixture(tmp_path, extra_witness=True)
    original = granted_movement.move
    for aid in (RIGHT, witness):
        monkeypatch.setitem(BASIC_MELEE, aid, BASIC_MELEE[AN])
    def legacy_move(engine, actor, candidate, intent, feet, ignored, **kwargs):
        # Test-only legacy representation, held through the native transaction;
        # the owned ability, service submission and movement stay unmodified.
        typed = set(engine.typed_actor_ids)
        engine.typed_actor_ids.difference_update((RIGHT, witness))
        try:
            assert set(granted_movement.legacy_reactors_along(engine, actor, candidate, [RIGHT, witness])) == {RIGHT, witness}
            original(engine, actor, candidate, intent, feet, ignored, **kwargs)
            assert engine._granted_movement_oa is None
        finally:
            engine.typed_actor_ids = typed
    monkeypatch.setattr(granted_movement, "move", legacy_move)
    answers = []
    for _ in range(12):
        result = act(t, mid, "Cause", answers, target_id=LEFT)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        q = result["reaction"]
        source = q["context"]["reaction_source_id"]
        if source == plug.INDEPENDENT_CHOICE:
            selected = ["maintain"]
        elif source == plug.BENEFIT_CHOICE:
            selected = ["move"]
        elif source == plug.MOVE_CHOICE:
            selected = [next(o["id"] for o in q["choice"]["options"] if "Walk to (2, 7)" in str(o))]
        else:
            raise AssertionError("Nonprovoking movement must not ask a reactor")
        answers.append({**q["context"], "selection": "USE", "option_ids": selected})
    else:
        raise AssertionError("too many movement choices")
    e = fresh(c, mid)
    assert e.state.actors[LEFT].position == Position(x=2, y=7)
    assert not any(ev.event_type == "REACTION_RESOLVED" and ev.actor_id in (RIGHT, witness) for ev in e.events)


def damage(c, t, mid, picks=None):
    return resolve(lambda a: act(t, mid, "Cause", a, target_id=LEFT), picks)


@pytest.mark.parametrize("benefit", ["temporary_hp", "move", "armament"])
def test_each_benefit_from_offturn_native_nonqi_save_and_cold_reload(tmp_path, benefit):
    c, t, mid = fixture(tmp_path)
    before = fresh(c, mid)
    actor = before.state.actors[LEFT]
    position, arm = actor.position, qi_path.armament_point(actor)
    qi = actor.resources[plug.QI]
    _, prompts = damage(c, t, mid, {plug.INDEPENDENT_CHOICE: ["maintain"], plug.BENEFIT_CHOICE: [benefit]})
    ask = next(p for p in prompts if p["context"]["reaction_source_id"] == plug.BENEFIT_CHOICE)
    assert {o["id"] for o in ask["choice"]["options"]} == {"temporary_hp", "move", "armament"}
    assert "Qi-Tempered Concentration" in str(ask) and "Prepare" in str(ask) and "Keeper" in str(ask)
    save_prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == plug.INDEPENDENT_CHOICE)
    assert "Reaction and 1 Qi" in str(save_prompt) and "DC 30" in str(save_prompt)
    after = fresh(c, mid)
    actor = after.state.actors[LEFT]
    assert actor.concentration is not None
    assert actor.resources[plug.QI] == qi - 1 and not actor.reaction_available
    assert actor.turn_flags[plug.USED] == after.state.round_number
    assert actor.temporary_hp == (20 if benefit == "temporary_hp" else 0)
    assert (actor.position != position) == (benefit == "move")
    assert (qi_path.armament_point(actor) != arm) == (benefit == "armament")
    assert len([e for e in after.events if e.source_definition_id == plug.FEATURE
                and e.payload.get("benefit_roll_id")]) == 1
    if benefit == "move":
        assert after.grid.distance_ft(position, actor.position) <= 5
        assert not [e for e in after.events if e.event_type == "REACTION_RESOLVED"
                    and e.actor_id == RIGHT]
    if benefit == "armament":
        assert after.grid.distance_ft(arm, qi_path.armament_point(actor)) <= 10
    # Cold continuation cannot repeat the reaction or award its benefit.
    damage(c, t, mid)
    assert len([e for e in fresh(c, mid).events if e.payload.get("benefit_roll_id")]) == 1


def test_ai_offturn_uses_own_independent_reaction_and_one_benefit(tmp_path):
    c, t, mid = fixture(tmp_path, ai=True)
    qi = fresh(c, mid).state.actors[LEFT].resources[plug.QI]
    _, prompts = damage(c, t, mid)
    assert not prompts
    actor = fresh(c, mid).state.actors[LEFT]
    assert actor.concentration is not None and actor.temporary_hp == 20
    assert actor.resources[plug.QI] == qi - 1


@pytest.mark.parametrize("kwargs", [{"owns": False}, {"nascent": False}, {"cl": 14}, {"cultivation": False}, {"disabled": True}])
def test_expansion_is_inert_without_both_owned_features_and_legal_source(tmp_path, kwargs):
    c, t, mid = fixture(tmp_path, **kwargs)
    qi = fresh(c, mid).state.actors[LEFT].resources[plug.QI]
    _, prompts = damage(c, t, mid)
    actor = fresh(c, mid).state.actors[LEFT]
    assert not prompts and actor.concentration is None
    assert actor.resources[plug.QI] == qi and actor.temporary_hp == 0


def test_base_independent_concentration_protects_qi_and_has_no_insight_reward(tmp_path):
    c, t, mid = fixture(tmp_path, owns=False, qi=True)
    _, prompts = damage(c, t, mid, {plug.INDEPENDENT_CHOICE: ["maintain"]})
    assert [p["context"]["reaction_source_id"] for p in prompts] == [plug.INDEPENDENT_CHOICE]
    actor = fresh(c, mid).state.actors[LEFT]
    assert actor.concentration is not None and actor.temporary_hp == 0


@pytest.mark.parametrize("con", [9, -30])
def test_decline_or_bonus_that_cannot_reach_dc_has_no_reward(tmp_path, con):
    c, t, mid = fixture(tmp_path, con=con)
    qi = fresh(c, mid).state.actors[LEFT].resources[plug.QI]
    picks = {plug.INDEPENDENT_CHOICE: [] if con == 9 else ["maintain"]}
    _, prompts = damage(c, t, mid, picks)
    assert not any(p["context"]["reaction_source_id"] == plug.BENEFIT_CHOICE for p in prompts)
    actor = fresh(c, mid).state.actors[LEFT]
    assert actor.concentration is None and actor.temporary_hp == 0
    assert actor.resources[plug.QI] == qi - int(con == -30)


def test_nascent_continuity_keeps_existing_turn_start_provider(tmp_path):
    def bundle(b):
        if b["actor_id"] == LEFT:
            for resource in b["actor_template"]["resources"]:
                if resource["resource_id"] == plug.QI:
                    resource["initial"] = 0
    c, t, mid = fight(tmp_path, [plug.NASCENT], bundle_edit=bundle,
        extra_actions=[("Spend Continuity Qi", {"effects": [{"type": "spend_resource", "resource_id": plug.QI,
                                                            "flat": 4, "applies_to": "self"}]})])
    # Genesis establishes the first actor before bundle turn hooks are loaded;
    # exercise a real committed turn transition, rather than testing genesis.
    turn(t, mid, RIGHT)
    turn(t, mid, LEFT)
    actor = fresh(c, mid).state.actors[LEFT]
    assert actor.resources[plug.QI] == 4
    assert actor.turn_flags["nascent_continuity_used_round_scene"] == 1
    resolve(lambda a: act(t, mid, "Spend Continuity Qi", a))
    turn(t, mid, RIGHT)
    turn(t, mid, LEFT)
    assert fresh(c, mid).state.actors[LEFT].resources[plug.QI] == 0
