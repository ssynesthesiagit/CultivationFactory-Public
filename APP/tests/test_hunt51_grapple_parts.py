"""Regression for the printed one-grapple-per-hand rule."""

import pytest

from tests.hunt51_grapple_support import fight, grapple, on_turn, send, verify_reloaded


def test_two_hands_refuse_third_ordinary_grapple(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "three-grapples", six=True)
    targets = ids[3:]
    for target in targets[:2]:
        on_turn(table, match, ids[0])
        send(table, match, grapple(target))
        send(table, match)
    on_turn(table, match, ids[0])
    menu = table.state(match)["menu"]
    available = [option for group in menu.get("actions", []) for option in group["options"]]
    held = [row for actor in service._load_session(match).engine.state.actors.values() for row in actor.conditions.values()
            if row.condition_id == "condition:typed.grappled" and row.source_actor_id == ids[0]]
    assert not any(grapple(targets[2])(option) for option in available), f"third Grapple offered: {[row.data for row in held]}"
    assert len(held) == 2
    assert {row.data.get("grappling_part") for row in held} == {"hand:left", "hand:right"}
    verify_reloaded(user, service, match)


def test_dragon_step_clinch_is_an_extra_grappling_part(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "dragon-step-clinch", six=True, dragon_clinch=True)
    targets = ids[3:]
    on_turn(table, match, ids[0])
    send(table, match, lambda option: "Dragon-Step Clinch: Maintain" in str(option.get("label", "")))
    for target in targets:
        on_turn(table, match, ids[0])
        send(table, match, grapple(target), reaction_pick=lambda choice: [
            next((option["id"] for option in choice["options"] if option["id"] == "body:dragon_step_clinch"),
                 choice["options"][0]["id"])
        ])
        if target != targets[-1]:
            send(table, match)
    holds = [row for actor in service._load_session(match).engine.state.actors.values() for row in actor.conditions.values()
             if row.condition_id == "condition:typed.grappled" and row.source_actor_id == ids[0]]
    assert len(holds) == 3
    assert "body:dragon_step_clinch" in {row.data.get("grappling_part") for row in holds}
    # Ending the feature through its owning action immediately releases only
    # the hold maintained by that body part.
    on_turn(table, match, ids[0])
    send(table, match, lambda option: "Dragon-Step Clinch: End" in str(option.get("label", "")))
    holds = [row for actor in service._load_session(match).engine.state.actors.values() for row in actor.conditions.values()
             if row.condition_id == "condition:typed.grappled" and row.source_actor_id == ids[0]]
    assert len(holds) == 2
    assert "body:dragon_step_clinch" not in {row.data.get("grappling_part") for row in holds}
    verify_reloaded(user, service, match)


def test_legacy_physical_holds_without_part_metadata_occupy_hands(tmp_path):
    from combat.ext.grapple_parts import _holds

    _user, service, _table, match, ids = fight(tmp_path, "legacy-grapple-part", six=True)
    engine = service._load_session(match).engine
    # This models a pre-metadata saved row while retaining the persisted
    # originating action used to distinguish physical Unarmed Strike Grapple.
    action = next(row for row in engine.action_catalog.values() if row.display_name == "Grapple"
                  and (row.parameters.get("typed") or {}).get("unarmed_option") == "grapple")
    held = engine.state.actors[ids[2]]
    engine._apply_condition(held, "condition:typed.grappled", action.source_definition_id, ids[0],
                            expires_on="UNTIL_REMOVED", data={"escape_dc": 30, "reach_ft": 5})
    holds = _holds(engine, engine.state.actors[ids[0]])
    assert len(holds) == 1
    assert holds[0][1].data.get("grappling_part") is None


def test_magical_grappled_row_does_not_consume_or_release_a_physical_part(tmp_path):
    from combat import ext
    from combat.ext.grapple_parts import _holds

    _user, service, table, match, ids = fight(tmp_path, "magical-grapple-inert", six=True)
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[3]))
    engine = service._load_session(match).engine
    actor = engine.state.actors[ids[0]]
    target = engine.state.actors[ids[4]]
    engine._apply_condition(target, "condition:typed.grappled", "effect:projectile-restraint", actor.entity_id,
                            expires_on="UNTIL_REMOVED", data={"label": "Projectile restraint"})
    assert len(_holds(engine, actor)) == 1
    assert all(row.data.get("label") != "Projectile restraint" for _, row in _holds(engine, actor))
    engine._apply_condition(actor, "condition:typed.incapacitated", "test:incapacity", actor.entity_id,
                            expires_on="UNTIL_REMOVED")
    ext.run("event", engine, "CONDITION_APPLIED", {"actor_id": actor.entity_id, "target_ids": (actor.entity_id,),
                                                        "payload": {"condition_id": "condition:typed.incapacitated"}})
    assert not any(row.condition_id == "condition:typed.grappled" and row.source_actor_id == actor.entity_id
                   for held in engine.state.actors.values() for row in held.conditions.values()
                   if (row.data or {}).get("grapple_source") == "physical")
    assert any(row.condition_id == "condition:typed.grappled" and row.source_actor_id == actor.entity_id
               and row.data.get("label") == "Projectile restraint" for row in target.conditions.values())


@pytest.mark.parametrize("ineligible_condition", ["prone", "restrained"])
def test_body_hold_ends_when_its_owner_becomes_prone_or_restrained(tmp_path, ineligible_condition):
    from combat import ext

    user, service, table, match, ids = fight(tmp_path, "ineligible-body-hold", six=True, dragon_clinch=True)
    on_turn(table, match, ids[0])
    send(table, match, lambda option: "Dragon-Step Clinch: Maintain" in str(option.get("label", "")))
    targets = ids[3:]
    for target in targets:
        on_turn(table, match, ids[0])
        send(table, match, grapple(target))
        if target != targets[-1]:
            send(table, match)
    session = service._load_session(match)
    engine = session.engine
    actor = engine.state.actors[ids[0]]
    assert any((row.data or {}).get("grappling_part") == "body:dragon_step_clinch"
               for held in engine.state.actors.values() for row in held.conditions.values()
               if row.condition_id == "condition:typed.grappled" and row.source_actor_id == actor.entity_id)
    condition_id = "condition:typed." + ineligible_condition
    engine._apply_condition(actor, condition_id, "test:eligibility", actor.entity_id,
                            expires_on="UNTIL_REMOVED")
    ext.run("event", engine, "CONDITION_APPLIED", {"actor_id": actor.entity_id, "target_ids": (actor.entity_id,),
                                                        "payload": {"condition_id": condition_id}})
    assert not any((row.data or {}).get("grappling_part") == "body:dragon_step_clinch"
                   for held in engine.state.actors.values() for row in held.conditions.values()
                   if row.condition_id == "condition:typed.grappled" and row.source_actor_id == actor.entity_id)
    assert not any(row.condition_id == "condition:typed.body_dragon_step_clinch" for row in actor.conditions.values())
