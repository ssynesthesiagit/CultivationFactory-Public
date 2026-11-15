"""Legal Draw/Stow setup shared by Barrage and multiple-Spear fixtures.

These tests exercise attack effects across several carried weapons. Prepare the
requested weapon through ordinary free equipment actions; never release a hold,
drop a shield, change hand counts, or bypass an eligibility hook.
"""
from combat.gate2_runtime_models import ActionIntent
from combat.ext.hand_occupancy import weapon_allowed, weapon_requirement


def ready_table_weapon(table, match_id, source):
    """Ready one attack's weapon through committed, reloadable Table actions."""
    for _ in range(12):
        state = table.state(match_id)
        engine = table.combat._load_session(match_id).engine
        action = engine.action_catalog[source]
        actor = engine.state.actors[action.owner_id]
        assert state["menu"]["actor_id"] == actor.entity_id
        if weapon_allowed(engine, actor, action) is not False:
            return
        identity, _ = weapon_requirement(engine, action)
        grips = [(candidate, row.parameters["equipment_grip"])
                 for candidate in engine.legal_candidates()
                 if (row := engine.action_catalog.get(candidate.source_definition_id)) is not None
                 and row.parameters.get("equipment_grip")]
        candidate = next((candidate for candidate, grip in grips
                          if grip["weapon"] == identity and grip["held"]), None)
        candidate = candidate or next((candidate for candidate, grip in grips
                                       if grip["weapon"] != identity and not grip["held"]), None)
        assert candidate is not None, "No legal equipment action can ready the requested weapon"
        result = table.act(match_id, candidate.candidate_id, candidate.decision_id,
                           candidate.state_version, state["last_sequence"])
        assert result["status"] == "COMMITTED"
    raise AssertionError("The requested weapon was not ready after legal equipment actions")


def ready_weapon(engine, name, actor_id=None):
    actor_id = actor_id or engine.state.current_actor_id
    action = next((row for row in engine.action_catalog.values()
                   if row.owner_id == actor_id and row.display_name == name), None)
    if action is None or not (requirement := weapon_requirement(engine, action)):
        return
    identity, _ = requirement
    actor = engine.state.actors[actor_id]
    for _ in range(12):
        if weapon_allowed(engine, actor, action) is not False:
            return
        choices = [(candidate, engine.action_catalog.get(candidate.source_definition_id))
                   for candidate in engine.legal_candidates() if candidate.actor_id == actor_id]
        grips = [(candidate, row.parameters['equipment_grip']) for candidate, row in choices
                 if row is not None and row.parameters.get('equipment_grip')]
        candidate = next((candidate for candidate, grip in grips
                          if grip['weapon'] == identity and grip['held']), None)
        candidate = candidate or next((candidate for candidate, grip in grips
                                       if grip['weapon'] != identity and not grip['held']), None)
        if candidate is None:
            return
        engine.execute_intent(ActionIntent(intent_id=f'fixture:ready:{len(engine.events)}',
            decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=actor_id,
            target_ids=candidate.target_ids, destination=candidate.destination))
