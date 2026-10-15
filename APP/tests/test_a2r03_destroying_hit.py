"""A2R03F7: a confirmed destroying hit still earns Echo and Predator Answer."""
import copy

import pytest

from combat.gate5_service import CombatService
from tests.test_a2r03_fix_round import _play_picked
from tests.test_a2r03_review_round5 import _owner_action, _take_owner_turn, _step
from tests.test_a2r11_foundations import (
    ROOT, FIGHTER, SERVICE_FOE, MARROW_BARE, ECHO,
    _marrow, _service_fight, _candidate, _engine,
)

PREY = "actor:factory.a2r03-beast-prey"


@pytest.mark.parametrize("paid_rider", [False, True])
@pytest.mark.parametrize("answer", ["temp_hp", "move", "DECLINE"])
def test_destroying_hit_keeps_echo_and_predator_choice_after_table_reload(
        tmp_path, monkeypatch, paid_rider, answer):
    def prepare(bundles):
        owner = next(b for b in bundles if b["actor_id"] == FIGHTER)
        for resource in owner["actor_template"]["resources"]:
            if resource["resource_id"] == ECHO:
                resource["initial"] = int(paid_rider)
        foe = next(b for b in bundles if b["actor_id"] == SERVICE_FOE)
        template = copy.deepcopy(foe["actor_template"])
        template.update(entity_id=PREY, owner_id=SERVICE_FOE,
                        display_name="summoned beast", primary_combatant=False,
                        creature_types=["Beast"], maximum_hp=6 if paid_rider else 1,
                        action_ids=[], reaction_ids=[])
        foe["summons"].append({
            "actor_id": PREY, "actor_template": template, "action_catalog": [],
            "typed_passives": [], "typed_reactions": [],
            "summon": {"owner": SERVICE_FOE, "group": "test:prey", "source": "test:prey",
                       "arrives": "start", "command": "free", "command_range_ft": 60,
                       "range_ft": 60, "concentration": False, "expected_damage": 0}})
        # A real scoped attack, with deterministic hit/damage and enough range
        # for the summon placement. A held Echo can destroy it with the paid
        # Strike rider; otherwise the primary damage destroys it.
        action = _owner_action(bundles, "Pack hunt", [{
            "type": "attack", "attack_kind": "ranged", "count": 1,
            "on_hit": [{"type": "damage", "applies_to": "target", "flat": 3,
                        "damage_types": ["piercing"]}], "on_miss": []}])
        action["parameters"]["typed"]["numbers"]["attack_bonus"] = 30
        action["parameters"]["typed"]["range_ft"] = 120

    combat, table, mid = _service_fight(
        tmp_path, monkeypatch, _marrow(), MARROW_BARE, prepare=prepare)
    _take_owner_turn(table, mid)
    before = _engine(combat, mid)
    assert before.state.actors[PREY].active
    start = len(before.events)
    position = before.state.actors[FIGHTER].position

    def pick(prompt):
        if prompt["reaction"] == "Pack-Marrow Strike":
            return "strike"
        options = [o["id"] for o in prompt.get("choice", {}).get("options", [])]
        if "temp_hp" in options:
            return answer
        return _step(prompt) if answer == "move" else "DECLINE"

    _, prompts = _play_picked(table, mid, _candidate(table, mid, "Pack hunt", PREY), pick)
    # A new service instance reads committed state and replays the actual
    # answers, rather than inspecting an in-memory preview engine.
    cold = _engine(CombatService(ROOT, tmp_path), mid)
    prey, owner = cold.state.actors[PREY], cold.state.actors[FIGHTER]
    assert prey.current_hp == 0 and not prey.active
    assert cold.state.actors[SERVICE_FOE].active  # combat continues
    assert cold.state.current_actor_id == FIGHTER
    assert owner.resources[ECHO] == 1
    predator = [p for p in prompts if "temp_hp" in [
        o["id"] for o in p.get("choice", {}).get("options", [])]]
    assert len(predator) == 1
    assert {o["id"] for o in predator[0]["choice"]["options"]} == {"temp_hp", "move"}
    assert all(word in predator[0]["moment"] for word in (
        "Predator Answer", "Pack hunt", "summoned beast"))
    assert owner.temporary_hp == (owner.proficiency_bonus if answer == "temp_hp" else 0)
    assert (owner.position != position) is (answer == "move")
    strikes = [p for p in prompts if p["reaction"] == "Pack-Marrow Strike"]
    assert len(strikes) == int(paid_rider)  # no spending newly generated Echo
    damage = [e for e in cold.events[start:] if e.event_type == "DAMAGE_COMMITTED"
              and PREY in e.target_ids]
    assert len(damage) == (2 if paid_rider else 1)
    assert damage[0].payload["hp_damage"] == (3 if paid_rider else 1)
