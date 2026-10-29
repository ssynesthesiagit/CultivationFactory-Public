"""Challenge owners keep their printed attack rules across table commit/reload."""
import pytest

from tests.test_c2_review import (
    ME, ATK, ALLY, action, answer, auto_send, end_turn, reload, send, table_fixture, until_turn,
)
from tests.test_riders_c2 import _sheet
from tests.test_riders_c2 import CH, G
from tests.test_riders_c8 import PT_ALL, sheet


@pytest.mark.parametrize("target,move_away,expected", [
    (ALLY, False, "DISADVANTAGE"),
    (ALLY, True, "NORMAL"),
    (ME, False, "NORMAL"),
])
@pytest.mark.parametrize("guardian", [False, True])
def test_deed_challenge_checks_actual_recipient_without_guardian_benefits(tmp_path, target, move_away, expected, guardian):
    def configure(bundles):
        for bundle in bundles:
            bundle["actor_template"]["maximum_hp"] = 500
            bundle["actor_template"]["armor_class"] = 0
            for resource in bundle["actor_template"]["resources"]:
                if resource["resource_id"] == "resource:named.credence":
                    resource["initial"] = 1

    caster = sheet([PT_ALL[0], PT_ALL[1], PT_ALL[3]], items=("tianxia.mortal.weapon.dao",), dc=50)
    caster["spheres_and_talents"] = {"learned_talent_record_ids": [CH, G + "PUNISHING_CHALLENGE", G + "FLUSH_OF_VICTORY"]}
    combat, table, mid = table_fixture(tmp_path, {
        ME: caster,
        ATK: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], weapon="tianxia.mortal.weapon.dao"),
        ALLY: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]),
    }, {ME: (3, 6), ATK: (4, 6), ALLY: (4, 7)}, configure=configure, seed="R23-DEED-CHALLENGE")
    until_turn(table, mid, ME)
    assert auto_send(combat, table, mid, action(table, mid, "Deed Follows Word: Challenge", ATK))["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    conditions = list(engine.state.actors[ATK].conditions.values())
    assert any(c.condition_id == "condition:typed.challenged"
               and c.source_definition_id == PT_ALL[3] for c in conditions)
    if guardian:
        assert send(table, mid, action(table, mid, "Challenge Practice", ATK))["status"] == "COMMITTED"
        conditions = list(reload(tmp_path, mid).state.actors[ATK].conditions.values())
        assert sum(c.condition_id == "condition:typed.challenged" for c in conditions) == 2
    end_turn(table, mid)
    until_turn(table, mid, ATK)
    if move_away:
        engine = reload(tmp_path, mid)
        cid = next(c.candidate_id for c in engine.legal_candidates() if c.display_name == "Move to 4,8")
        result = send(table, mid, cid)
        answers = []
        for _ in range(8):
            if result["status"] == "COMMITTED":
                break
            assert result["status"] == "REACTION_REQUIRED"
            answers.append(answer(result, "DECLINE"))
            result = send(table, mid, cid, answers)
        assert result["status"] == "COMMITTED"
    before = len(reload(tmp_path, mid).events)
    assert send(table, mid, action(table, mid, "Dao (Saber / Broadsword) attack", target))["status"] == "COMMITTED"
    events = reload(tmp_path, mid).events[before:]
    rolled = [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ATK]
    assert rolled and rolled[-1].payload["mode"] == ("ADVANTAGE" if guardian and target == ME else expected)
    punished = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == ME
                and e.payload.get("damage_type") in ("PSYCHIC", "RADIANT")]
    assert bool(punished) == (guardian and target == ALLY and not move_away)
