"""Grapple continuations across the actual table transaction and disk boundary."""

import pytest

from combat import concentration, ext
from combat.gate5_service import CombatService
from tests.hunt51_grapple_support import fight, grapple, on_turn, send, verify_reloaded

BODY = "body:dragon_step_clinch"
SELF = "condition:typed.body_dragon_step_clinch"


@pytest.mark.parametrize("condition", ["prone", "restrained"])
def test_other_owning_feature_keeps_eligible_body_part(tmp_path, monkeypatch, condition):
    user, service, table, match, ids = fight(tmp_path, "other-body-" + condition, six=True,
                                            fixture_conditions=(condition,))
    part = "body:test_tail"
    ext.effects()
    def tail(engine, actor):
        return [{"id": part, "label": "Tail hold"}] if actor.entity_id == ids[0] else None
    monkeypatch.setitem(ext._HOOKS, "grappling_body_parts", [*ext._HOOKS.get("grappling_body_parts", []), tail])
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[3]), reaction_pick=lambda choice: [part])
    send(table, match)
    on_turn(table, match, ids[4])
    send(table, match, lambda option: "Fixture: " + condition.title() in str(option.get("label", ""))
         and option.get("target_ids") == [ids[0]])
    engine = reload(user, service, match)
    assert holds(engine, ids[0])[0].data["grappling_part"] == part


@pytest.mark.parametrize("upgraded", [False, True])
def test_clinch_choice_describes_effective_speed_cost(tmp_path, upgraded):
    user, service, table, match, ids = fight(tmp_path, "speed-cost-" + str(upgraded), six=True,
                                            dragon_clinch=True, heaven_clinch=upgraded)
    def choose(choice):
        label = next(option["label"] for option in choice["options"] if option["id"] == BODY)
        assert ("Speed unchanged" in label) == upgraded
        assert ("10 feet" in label) == (not upgraded)
        return [BODY]
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[3]), reaction_pick=choose)
    engine = reload(user, service, match)
    assert (0 if upgraded else -10) in ext.run("speed", engine, engine.state.actors[ids[0]])


def holds(engine, source):
    return [row for actor in engine.state.actors.values() for row in actor.conditions.values()
            if row.condition_id == "condition:typed.grappled" and row.source_actor_id == source]


def reload(user, service, match):
    verify_reloaded(user, service, match)
    return CombatService(service.source_root, user)._load_session(match).engine


def pick_body(choice):
    if any(option["id"] == BODY for option in choice["options"]):
        label = next(option["label"] for option in choice["options"] if option["id"] == BODY)
        assert "10 feet" in label and "Advantage" in label and "Opened" in label
        assert "no Action" in label and "resource cost" in label
        return [BODY]
    return [choice["options"][0]["id"]]


def test_saved_legacy_holds_occupy_hands_and_end_with_concentration(tmp_path, monkeypatch):
    user, service, table, match, ids = fight(tmp_path, "saved-legacy", six=True,
                                            heavenquake=True, concentration=True)
    on_turn(table, match, ids[0])
    send(table, match, lambda option: "Burning Weapon" in str(option.get("label", "")))
    send(table, match)
    # Build a pre-field save through real actions, with only the new metadata
    # hook absent. No journal/hash rewriting, cached-row edit or engine patch.
    from combat.ext.grapple_parts import record_grappling_part

    ext.effects()
    with monkeypatch.context() as legacy:
        legacy.setitem(ext._HOOKS, "condition_state",
                       [hook for hook in ext._HOOKS["condition_state"] if hook is not record_grappling_part])
        for target in (ids[3], ids[5]):
            on_turn(table, match, ids[0])
            send(table, match, grapple(target))
            send(table, match)
    engine = reload(user, service, match)
    assert len(holds(engine, ids[0])) == 2
    assert all("grappling_part" not in row.data for row in holds(engine, ids[0]))
    assert concentration.sources(engine.state.actors[ids[0]])
    on_turn(table, match, ids[0])
    assert not any(grapple(ids[4])(option) for group in table.state(match)["menu"]["actions"]
                   for option in group["options"])
    send(table, match)
    on_turn(table, match, ids[4])  # Heavenquake owner in the six-actor roster
    send(table, match, lambda option: "One-Inch Heavenquake" in str(option.get("label", ""))
         and option.get("target_ids") == [ids[0]])
    engine = reload(user, service, match)
    assert any(row.condition_id == "condition:typed.stunned" for row in engine.state.actors[ids[0]].conditions.values())
    assert not holds(engine, ids[0])
    assert concentration.sources(engine.state.actors[ids[0]]) == []


@pytest.mark.parametrize("condition", ["prone", "restrained", "incapacitated", "stunned"])
def test_committed_condition_releases_body_but_preserves_hand_and_nonphysical(tmp_path, condition):
    user, service, table, match, ids = fight(tmp_path, "persisted-" + condition, six=True,
                                            dragon_clinch=True, fixture_conditions=(condition, "grappled"))
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[3]), reaction_pick=pick_body)
    engine = reload(user, service, match)
    assert holds(engine, ids[0])[0].data["grappling_part"] == BODY
    send(table, match)
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[5]))
    send(table, match)
    on_turn(table, match, ids[0])
    send(table, match, lambda option: "Fixture: Grappled" in str(option.get("label", ""))
         and option.get("target_ids") == [ids[4]])
    send(table, match)
    engine = reload(user, service, match)
    assert len(holds(engine, ids[0])) == 3  # two physical, one nonphysical
    on_turn(table, match, ids[4])
    send(table, match, lambda option: "Fixture: " + condition.title() in str(option.get("label", ""))
         and option.get("target_ids") == [ids[0]])
    engine = reload(user, service, match)
    actor = engine.state.actors[ids[0]]
    assert any(row.condition_id == "condition:typed." + condition for row in actor.conditions.values())
    assert not any(row.condition_id == SELF for row in actor.conditions.values())
    remaining = holds(engine, ids[0])
    assert not any(row.data.get("grappling_part") == BODY for row in remaining)
    assert len(remaining) == (2 if condition in ("prone", "restrained") else 1)
    # The same grappler's nonphysical restraint survives its incapacitation.
    assert any("grappling_part" not in row.data for row in remaining)
    if condition in ("prone", "restrained"):
        from combat.ext.grapple_parts import _free_parts
        assert BODY not in {part["id"] for part in _free_parts(engine, actor)}


@pytest.mark.parametrize("path", ["manual", "ask_ai", "automatic"])
def test_inactive_owner_selects_each_hold_on_manual_and_ai_paths(tmp_path, monkeypatch, path):
    user, service, table, match, ids = fight(tmp_path, "choice-" + path, six=True,
                                            dragon_clinch=True, ask=path != "automatic",
                                            fixture_conditions=("test_response",) if path == "ask_ai" else ())
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    assert not any(row.condition_id == SELF for row in engine.state.actors[ids[0]].conditions.values())
    asked = []
    if path == "manual":
        def choose(choice):
            asked.append(choice)
            return pick_body(choice)
        send(table, match, grapple(ids[3]), reaction_pick=choose)
    else:
        from tests.hunt12_support import candidate, send as selected_send
        if path == "ask_ai":
            # A synthetic trigger makes the Manual owner's shipped Unarmed
            # Grapple resolve during an AI turn. Choice handling, rolls,
            # condition application, transaction and replay remain production.
            from combat.typed_executor import Context, run_effects

            def response(ctx, subject, effect):
                if effect.get("condition") != "test_response":
                    return None
                owner = ctx.engine.state.actors[ids[0]]
                action = next(row for row in ctx.engine.action_catalog.values()
                              if row.owner_id == owner.entity_id and row.display_name == "Grapple")
                typed = action.parameters["typed"]
                sub = Context(ctx.engine, owner, action, ctx.intent, typed, [ctx.actor], ctx.actor)
                run_effects(sub, typed["effects"])
                return False  # the fixture is a trigger, not a persisted condition

            ext.effects()
            monkeypatch.setitem(ext._HOOKS, "condition_attempt", [*ext._HOOKS.get("condition_attempt", []), response])
            on_turn(table, match, ids[4])
            service.set_controller_mode(match, actor_id=ids[4], controller_mode="LOCAL_AUTO")
            selected = candidate(service, match, lambda row: "Fixture: Test_Response" in row.display_name
                                 and row.target_ids == (ids[0],))
        else:
            service.set_controller_mode(match, actor_id=ids[0], controller_mode="LOCAL_AUTO")
            selected = candidate(service, match, lambda row: row.display_name == "Grapple" and row.target_ids == (ids[3],))
        answers = []
        for _ in range(20):
            result = selected_send(service, table, match, selected, answers, auto=True)
            if result["status"] != "REACTION_REQUIRED":
                break
            reaction = result["reaction"]
            answer = {**reaction["context"], "selection": "DECLINE"}
            if reaction.get("choice") and not reaction["choice"].get("allow_decline"):
                asked.append(reaction["choice"])
                answer.update(selection="USE", option_ids=pick_body(reaction["choice"]))
            answers.append(answer)
        assert result["status"] == "COMMITTED", result
    engine = reload(user, service, match)
    row = holds(engine, ids[0])[0]
    if path == "automatic":
        assert asked == [] and row.data["grappling_part"] == "hand:left"
        assert not any(row.condition_id == SELF for row in engine.state.actors[ids[0]].conditions.values())
        # With both hands occupied, automatic selection must use and activate
        # the newly available body option, without a player prompt.
        for target in ids[4:]:
            service.set_controller_mode(match, actor_id=ids[0], controller_mode="MANUAL")
            send(table, match)
            on_turn(table, match, ids[0])
            service.set_controller_mode(match, actor_id=ids[0], controller_mode="LOCAL_AUTO")
            selected = candidate(service, match, lambda item: item.display_name == "Grapple" and item.target_ids == (target,))
            assert selected_send(service, table, match, selected, auto=True)["status"] == "COMMITTED"
            engine = reload(user, service, match)
        assert {row.data["grappling_part"] for row in holds(engine, ids[0])} == {"hand:left", "hand:right", BODY}
        assert any(row.condition_id == SELF for row in engine.state.actors[ids[0]].conditions.values())
    else:
        assert asked and row.data["grappling_part"] == BODY
        assert row.data["clinch_escape_advantage"] == 1
        assert any(row.condition_id == SELF for row in engine.state.actors[ids[0]].conditions.values())
        target = ids[4] if path == "ask_ai" else ids[3]
        assert "ADVANTAGE" in ext.run("escape_mode", engine, engine.state.actors[target], [row])


def test_two_hands_offer_inactive_body_then_end_releases_only_body(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "inactive-third", six=True, dragon_clinch=True)
    for target in ids[3:5]:
        on_turn(table, match, ids[0])
        send(table, match, grapple(target))  # choose the default free hand
        send(table, match)
    engine = reload(user, service, match)
    assert not any(row.condition_id == SELF for row in engine.state.actors[ids[0]].conditions.values())
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[5]), reaction_pick=pick_body)
    assert len(holds(reload(user, service, match), ids[0])) == 3
    send(table, match, lambda option: "Dragon-Step Clinch: End" in str(option.get("label", "")))
    engine = reload(user, service, match)
    assert len(holds(engine, ids[0])) == 2
    assert not any(row.condition_id == SELF for row in engine.state.actors[ids[0]].conditions.values())


def test_already_opened_clinch_has_no_escape_advantage_and_speed_cost_ends(tmp_path):
    from combat.typed_executor import bears_mark

    user, service, table, match, ids = fight(tmp_path, "opened-clinch", six=True, dragon_clinch=True)
    on_turn(table, match, ids[0])
    send(table, match, lambda option: "Unarmed Strike" in str(option.get("label", ""))
         and "Grapple" not in str(option.get("label", "")) and "Shove" not in str(option.get("label", ""))
         and option.get("target_ids") == [ids[3]])
    engine = reload(user, service, match)
    assert bears_mark(engine.state.actors[ids[3]], ids[0], "Opened")
    send(table, match)
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[3]), reaction_pick=pick_body)
    engine = reload(user, service, match)
    row = holds(engine, ids[0])[0]
    assert row.data["clinch_escape_advantage"] == 0
    assert "ADVANTAGE" not in ext.run("escape_mode", engine, engine.state.actors[ids[3]], [row])
    assert -10 in ext.run("speed", engine, engine.state.actors[ids[0]])
    send(table, match, lambda option: "Dragon-Step Clinch: End" in str(option.get("label", "")))
    engine = reload(user, service, match)
    assert not holds(engine, ids[0])
    assert -10 not in ext.run("speed", engine, engine.state.actors[ids[0]])


def test_body_hold_range_release_also_ends_its_speed_cost(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "clinch-range-release", six=True, dragon_clinch=True)
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[3]), reaction_pick=pick_body)
    engine = reload(user, service, match)
    assert -10 in ext.run("speed", engine, engine.state.actors[ids[0]])
    send(table, match)
    on_turn(table, match, ids[0])
    send(table, match, lambda option: "Shove: Push 5 ft" in str(option.get("label", ""))
         and option.get("target_ids") == [ids[3]])
    engine = reload(user, service, match)
    assert not holds(engine, ids[0])
    assert not any(row.condition_id == SELF for row in engine.state.actors[ids[0]].conditions.values())
    assert -10 not in ext.run("speed", engine, engine.state.actors[ids[0]])
