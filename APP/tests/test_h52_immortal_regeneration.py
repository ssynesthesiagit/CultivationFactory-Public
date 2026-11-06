"""Immortal Body regeneration through real TabletopService commits."""
import pytest

from combat.gate5_service import CombatService
from tests.h52_turn_start_support import PEOPLE, ROOT, commit, engine_at, fight, next_action


def test_immortal_body_regenerates_after_committed_table_damage(tmp_path):
    combat, table, match_id, owner_id = fight(tmp_path, "ning")
    engine = engine_at(combat, match_id)
    owner = engine.state.actors[owner_id]
    assert owner.maximum_hp > 0 and owner.current_hp == owner.maximum_hp
    damaged_turns = None
    for _ in range(600):
        next_action(table, match_id, owner_id, attack_owner=True, combat=combat)
        engine = engine_at(combat, match_id)
        owner = engine.state.actors[owner_id]
        if damaged_turns is None and owner.current_hp < owner.maximum_hp:
            damaged_turns = owner.turns_started
        if damaged_turns is not None and owner.turns_started > damaged_turns:
            heals = [event for event in engine.events if event.event_type == "HEALING_APPLIED"
                     and event.source_definition_id.endswith("feature.immortal_body") and event.target_ids == (owner_id,)]
            assert heals and heals[-1].payload["offered"] == 20
            assert heals[-1].payload["after"] > heals[-1].payload["before"]
            break
    else:
        pytest.fail("the real table did not advance Ning Kai through a damaged turn start")
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert reloaded.mechanical.replay()["status"] == "PASS"
    assert reloaded.engine.state.model_dump(mode="json") == engine.state.model_dump(mode="json")



def test_immortal_regeneration_obeys_cannot_regain_hp_and_healing_reduction(tmp_path):
    """Jia Fengshan's Grave Chill: "cannot regain HP until the start of your next turn" on a failed Constitution save,
    "healing it receives before the start of your next turn is reduced by your Proficiency Bonus" on a success. Ning
    Kai's next turn starts before Jia's, so Immortal Regeneration (the shared healing path) restores nothing after a
    failed save and 20 minus Jia's Proficiency Bonus after a successful one."""
    combat, table, match_id, owner_id = fight(tmp_path, "ning", ["jia"])
    jia = "actor:factory." + PEOPLE["jia"]

    def grave_chill(menu):
        for group in menu.get("actions", []):
            if str(group.get("source_definition_id")).endswith("TAL_DEATH_GRAVE_CHILL"):
                return next(row["candidate_id"] for row in group.get("options", []) if owner_id in row.get("target_ids", []))
        return None

    seen = set()
    for _ in range(120):
        engine = engine_at(combat, match_id)
        before = engine.state.actors[owner_id]
        restriction = next((str(modifier.value) for modifier in before.modifiers.values()
                            if modifier.target_field == "healing_reduction"), None)
        turns, damaged = before.turns_started, before.current_hp < before.maximum_hp
        menu = table.state(match_id)["menu"]
        commit(table, match_id, menu, grave_chill(menu) if menu["actor_id"] == jia else None)
        engine = engine_at(combat, match_id)
        owner = engine.state.actors[owner_id]
        if owner.turns_started == turns or restriction is None or not damaged:
            continue
        latest = [event for event in engine.events if event.event_type == "HEALING_APPLIED"
                  and event.source_definition_id.endswith("feature.immortal_body") and event.target_ids == (owner_id,)][-1]
        assert latest.payload["before"] == before.current_hp
        if restriction == "none":  # cannot regain HP
            assert latest.payload["offered"] == 0 and latest.payload["after"] == before.current_hp
        else:
            assert restriction.startswith("minus:")
            offered = 20 - int(restriction.split(":")[1])
            assert latest.payload["offered"] == offered
            assert latest.payload["after"] == min(owner.maximum_hp, before.current_hp + offered)
        seen.add(restriction.split(":")[0])
        if seen == {"none", "minus"}:
            break
    else:
        pytest.fail(f"Grave Chill did not deny and reduce Ning Kai's regeneration at the table (saw {sorted(seen)})")
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert reloaded.mechanical.replay()["status"] == "PASS"
    assert reloaded.engine.state.model_dump(mode="json") == engine.state.model_dump(mode="json")
