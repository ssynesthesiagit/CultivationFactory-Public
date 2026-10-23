"""Pack Attack goes through real table transactions and a fresh service reload."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_r9i_karma_persistence import act, end_turn

OWNER = "actor:factory.auto29-owner"
FOE = "actor:factory.auto29-foe"
PACK = "tianxia.talent.beastmastery.pack_attack"


@pytest.mark.parametrize("owns,beasts,expected", [(True, 2, "ADVANTAGE"), (True, 1, "NORMAL"), (False, 2, "NORMAL")])
def test_pack_attack_table_commit_and_reload(tmp_path, owns, beasts, expected):
    owner = compile_character(sheet(["TAL_BEASTMASTERY_BEAST_TAMER", *([PACK] if owns else [])]),
                              actor_id=OWNER, summon_plan={"beasts": ["wolf"] * beasts, "mount": ""})
    foe = compile_character(sheet([]), actor_id=FOE)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        [owner, foe], [OWNER, FOE], {OWNER: "team:factory", FOE: "team:opponents"},
        {OWNER: {"x": 3, "y": 6}, FOE: {"x": 3, "y": 4}},
        combat.factory_arenas()["battlefield:factory_pillar_arena"], [OWNER], [FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, match_seed="AUTO29",
        display_name="Pack Attack", maximum_rounds=10)["match_id"]
    attacker = owner["summons"][0]["actor_id"]
    for _ in range(8):
        if table.state(mid)["menu"]["actor_id"] == attacker:
            break
        end_turn(table, mid)
    assert table.state(mid)["menu"]["actor_id"] == attacker
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                     if c.display_name == "Bite" and c.target_ids == (FOE,))
    assert act(table, mid, candidate.candidate_id)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == attacker]
    assert rolls and rolls[-1].payload["mode"] == expected
    assert loaded.engine.state.actors[attacker].summon["owner"] == OWNER
    assert loaded.mechanical.replay()["status"] == "PASS"
